"""التحصيل من الفاتورة بس.

An accepted quotation becomes an invoice; money is collected on the invoice only: the salesperson records what he
received (pending: in no cashbox, counted nowhere), the accounts confirm it into a cashbox (a cash receipt on the
invoice, and on its work order) or refuse it with a reason. Once the confirmed money reaches the deposit, the invoice
becomes a work order («تحويل لأمر تصنيع»); every later payment is still collected on the invoice.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.common import Record
from app.core.audit import audit, snapshot
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.invoicing.models import Collection, Invoice
from app.modules.org.models import Branch
from app.modules.sales import ownership
from app.modules.sales.pricing import money
from app.tenancy.context import require

router = APIRouter(tags=["collections"])

METHODS = "^(cash|transfer|cheque|card)$"


class CollectionIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    method: str = Field("cash", pattern=METHODS)
    reference: str = Field("", max_length=100)
    note: str = Field("", max_length=1000)


class CollectionOut(Record):
    number: str
    invoice_id: uuid.UUID
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    owner_id: uuid.UUID | None
    amount: Decimal
    method: str
    reference: str
    note: str
    status: str
    decided_at: datetime | None
    decided_by: uuid.UUID | None
    reject_reason: str
    cash_transaction_id: uuid.UUID | None
    invoice_number: str | None = None
    invoice_total: Decimal | None = None


def _invoice(db, ctx, inv_id, perm: str) -> Invoice:
    inv = db.get(Invoice, inv_id)
    if inv is None or inv.deleted_at is not None:
        raise NotFound("Invoice not found")
    ctx.require(perm, inv.branch_id)
    ownership.check(ctx, inv)
    return inv


def sums(db, inv: Invoice) -> tuple[Decimal, Decimal]:
    """(confirmed, pending) collections of the invoice."""
    rows = dict(db.execute(select(Collection.status, func.coalesce(func.sum(Collection.amount), 0))
                           .where(Collection.invoice_id == inv.id).group_by(Collection.status)).all())
    return money(Decimal(rows.get("confirmed", 0))), money(Decimal(rows.get("pending", 0)))


def _out(db, c: Collection) -> CollectionOut:
    out = CollectionOut.model_validate(c)
    inv = db.get(Invoice, c.invoice_id)
    out.invoice_number, out.invoice_total = inv.number, inv.total
    return out


@router.post("/invoices/{inv_id}/collections", response_model=CollectionOut, status_code=201)
def record_collection(inv_id: uuid.UUID, body: CollectionIn, dc=Depends(require("collections.create"))):
    """The salesperson received money on the invoice: it waits for the accounts."""
    from app.modules.invoicing.router import invoice_out
    from app.modules.notifications.router import alert, customer_name, recipients

    db, ctx = dc
    inv = _invoice(db, ctx, inv_id, "collections.create")
    if inv.status != "issued":
        raise Conflict("Collect on an issued invoice", code="INVOICE_NOT_ISSUED")
    _, pending = sums(db, inv)
    remaining = money(invoice_out(db, inv).balance - pending)
    if body.amount > remaining:
        raise ValidationFailed("More than what is left on the invoice", code="COLLECTION_TOO_LARGE",
                               details={"remaining": str(remaining)})
    branch = db.get(Branch, inv.branch_id)
    c = Collection(number=next_number(db, "collection", "CL", branch.code), invoice_id=inv.id,
                   customer_id=inv.customer_id, branch_id=inv.branch_id, owner_id=inv.owner_id or ctx.user_id,
                   **body.model_dump())
    db.add(c)
    db.flush()
    audit(db, c, "create")
    alert(db, ctx, "accounts", inv.branch_id, f"تحصيل مستني تأكيدك: {c.amount} على فاتورة {inv.number}",
          customer_name(db, inv.customer_id), "treasury?tab=collections",
          users=recipients(db, "collections.confirm", inv.branch_id))
    db.commit()
    return _out(db, c)


@router.get("/invoices/{inv_id}/collections", response_model=list[CollectionOut])
def invoice_collections(inv_id: uuid.UUID, dc=Depends(require("invoices.read"))):
    db, ctx = dc
    inv = _invoice(db, ctx, inv_id, "invoices.read")
    return [_out(db, c) for c in db.scalars(select(Collection).where(Collection.invoice_id == inv.id)
                                           .order_by(Collection.created_at))]


@router.get("/collections", response_model=list[CollectionOut])
def list_collections(status: str | None = "pending", dc=Depends(require("invoices.read"))):
    """The accounts' list (pending by default); a salesperson sees his own."""
    from app.modules.crm.router import branch_scope

    db, ctx = dc
    stmt = select(Collection).order_by(Collection.created_at.desc())
    if status:
        stmt = stmt.where(Collection.status == status)
    stmt = ownership.scope(branch_scope(stmt, ctx, "invoices.read", Collection.branch_id), ctx, Collection.owner_id)
    return [_out(db, c) for c in db.scalars(stmt.limit(500))]


class ConfirmIn(BaseModel):
    version: int
    cashbox_id: uuid.UUID


class RejectIn(BaseModel):
    version: int
    reason: str = Field(min_length=3, max_length=1000)


def _decide(db, ctx, coll_id, version) -> tuple[Collection, Invoice]:
    from app.core.audit import check_version

    c = db.scalar(select(Collection).where(Collection.id == coll_id).with_for_update())
    if c is None:
        raise NotFound("Collection not found")
    ctx.require("collections.confirm", c.branch_id)
    check_version(c, version)
    if c.status != "pending":
        raise Conflict("Already decided", code="COLLECTION_DECIDED")
    return c, db.get(Invoice, c.invoice_id)


@router.post("/collections/{coll_id}/confirm", response_model=CollectionOut)
def confirm_collection(coll_id: uuid.UUID, body: ConfirmIn, dc=Depends(require("collections.confirm"))):
    """The accounts received it: a cash receipt into the cashbox, on the invoice (and its work order)."""
    from app.modules.crm.router import get_or_404
    from app.modules.notifications.router import alert, customer_name
    from app.modules.treasury.models import Cashbox
    from app.modules.treasury.router import post_cash

    db, ctx = dc
    c, inv = _decide(db, ctx, coll_id, body.version)
    if inv.status != "issued":
        raise Conflict("The invoice is cancelled", code="INVOICE_NOT_ISSUED")
    box = get_or_404(db, Cashbox, body.cashbox_id)
    ctx.require("collections.confirm", box.branch_id)
    before = snapshot(c)
    tx = post_cash(db, ctx, box, direction="in", amount=c.amount, party_type="customer", method=c.method,
                   party_id=c.customer_id, invoice_id=inv.id, work_order_id=inv.work_order_id,
                   reference=c.reference, note=f"تحصيل {c.number}" + (f" · {c.note}" if c.note else ""))
    c.status, c.decided_at, c.decided_by, c.cash_transaction_id = "confirmed", utcnow(), ctx.user_id, tx.id
    audit(db, c, "update", before, note="الحسابات أكدت التحصيل")
    users = {u for u in (c.created_by, c.owner_id) if u}
    alert(db, ctx, "sales", inv.branch_id, f"الحسابات أكدت تحصيل {c.amount} على فاتورة {inv.number}",
          customer_name(db, inv.customer_id), f"invoices/{inv.id}", users=users)
    db.commit()
    return _out(db, c)


@router.post("/collections/{coll_id}/reject", response_model=CollectionOut)
def reject_collection(coll_id: uuid.UUID, body: RejectIn, dc=Depends(require("collections.confirm"))):
    from app.modules.notifications.router import alert, customer_name

    db, ctx = dc
    c, inv = _decide(db, ctx, coll_id, body.version)
    before = snapshot(c)
    c.status, c.decided_at, c.decided_by, c.reject_reason = "rejected", utcnow(), ctx.user_id, body.reason
    audit(db, c, "update", before, note="الحسابات رفضت التحصيل")
    users = {u for u in (c.created_by, c.owner_id) if u}
    alert(db, ctx, "sales", inv.branch_id, f"الحسابات رفضت تحصيل {c.amount} على فاتورة {inv.number}",
          f"{customer_name(db, inv.customer_id)} · {body.reason}", f"invoices/{inv.id}", users=users)
    db.commit()
    return _out(db, c)


class ToOrderIn(BaseModel):
    version: int
    due_date: date | None = None


@router.post("/invoices/{inv_id}/work-order")
def invoice_to_work_order(inv_id: uuid.UUID, body: ToOrderIn, dc=Depends(require("workorders.create"))):
    """«تحويل لأمر تصنيع»: once the accounts confirmed the deposit on the invoice. The sale counts as confirmed
    (the accounts confirmed its money), and the order's paid amount is what the invoice collected."""
    from app.core.audit import check_version
    from app.modules.invoicing.router import invoice_out
    from app.modules.org.settings import get_company_settings
    from app.modules.production.router import FromQuotationIn, _wo_out, order_from_quotation
    from app.modules.sales.models import Quotation

    db, ctx = dc
    inv = _invoice(db, ctx, inv_id, "workorders.create")
    check_version(inv, body.version)
    if inv.status != "issued" or inv.quotation_id is None:
        raise Conflict("An issued invoice of an accepted quotation", code="INVOICE_NOT_ISSUED")
    if inv.work_order_id is not None:
        raise Conflict("Already a work order", code="QUOTE_ALREADY_ORDERED")
    paid = invoice_out(db, inv).paid_amount
    deposit = money(inv.total * get_company_settings(db, ctx.company_id).deposit_pct / 100)
    if paid < deposit:
        raise Conflict("The deposit is not collected and confirmed yet", code="DEPOSIT_REQUIRED",
                       details={"deposit": str(deposit), "paid": str(paid)})
    q = db.get(Quotation, inv.quotation_id)
    wo = order_from_quotation(db, ctx, q, FromQuotationIn(quotation_id=q.id, due_date=body.due_date,
                                                         deposit_required=deposit), notify_accounts=False)
    before = snapshot(inv)
    inv.work_order_id = wo.id
    audit(db, inv, "update", before, note=f"اتحولت لأمر تصنيع {wo.number}")
    wo.paid_amount = paid
    wo.total = inv.total
    wo.sale_status, wo.sale_approved_at, wo.sale_approved_by = "approved", utcnow(), ctx.user_id
    wo.sale_approval_note = "العربون اتحصّل على الفاتورة واتأكد من الحسابات"
    db.commit()
    return _wo_out(db, wo, ctx=ctx)
