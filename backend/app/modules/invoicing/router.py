from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.modules.deletions.router import deletable
from app.api.common import DeleteResult, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.models import Customer
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.hr.router import salesperson_for
from app.modules.invoicing.models import Invoice, InvoiceLine
from app.modules.library.models import ProductModel
from app.modules.library.service import model_image
from app.modules.org.models import Branch
from app.modules.org.settings import get_company_settings
from app.modules.production.models import WorkOrder, WorkOrderItem
from app.modules.sales.models import Quotation, QuotationLine
from app.modules.sales.pricing import money
from app.modules.treasury.models import CashTransaction
from app.tenancy.context import require

router = APIRouter(tags=["invoicing"])
EDIT_PERM, READ_PERM = "treasury.write", "treasury.read"


class LineIn(BaseModel):
    kind: str = Field("product", pattern="^(product|service|other)$")
    description: str = ""
    location: str = ""
    model_id: uuid.UUID | None = None
    opening_width_mm: Decimal | None = Field(None, gt=0)
    opening_height_mm: Decimal | None = Field(None, gt=0)
    color_code: str | None = None
    glass_material_code: str | None = None
    qty: Decimal = Field(Decimal(1), gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_pct: Decimal = Field(Decimal(0), ge=0, le=100)


class LineUpdate(VersionedUpdate):
    description: str | None = None
    location: str | None = None
    qty: Decimal | None = Field(None, gt=0)
    unit_price: Decimal | None = Field(None, ge=0)
    discount_pct: Decimal | None = Field(None, ge=0, le=100)


class InvoiceIn(BaseModel):
    customer_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    work_order_id: uuid.UUID | None = None     # copy the order's windows and prices
    quotation_id: uuid.UUID | None = None      # or an accepted quotation's lines
    discount_amount: Decimal = Field(Decimal(0), ge=0)
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    due_days: int = Field(0, ge=0)
    notes: str = ""
    terms: str | None = None
    salesperson_id: uuid.UUID | None = None
    lines: list[LineIn] = []


class InvoiceUpdate(VersionedUpdate):
    discount_amount: Decimal | None = Field(None, ge=0)
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    due_date: date | None = None
    notes: str | None = None
    terms: str | None = None
    salesperson_id: uuid.UUID | None = None


class LineOut(Record):
    position: int
    kind: str
    description: str
    location: str
    model_id: uuid.UUID | None
    model_name: str
    model_image_id: uuid.UUID | None
    opening_width_mm: Decimal | None
    opening_height_mm: Decimal | None
    width_mm: Decimal | None
    height_mm: Decimal | None
    color_code: str | None
    glass_material_code: str | None
    params: dict
    drawing: list
    qty: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    discount_amount: Decimal
    line_total: Decimal


class InvoiceOut(Record):
    number: str | None
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    work_order_id: uuid.UUID | None
    quotation_id: uuid.UUID | None
    salesperson_id: uuid.UUID | None = None
    status: str
    issue_date: date | None
    due_date: date | None
    lines_total: Decimal
    lines_discount: Decimal
    discount_amount: Decimal
    tax_pct: Decimal
    tax_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    balance: Decimal = Decimal(0)
    notes: str
    terms: str
    cancel_reason: str
    lines: list[LineOut] = []


def _lines(db, inv) -> list[InvoiceLine]:
    return list(db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.position)))


def _paid(db, inv) -> Decimal:
    signed = case((CashTransaction.direction == "in", CashTransaction.amount), else_=-CashTransaction.amount)
    return db.scalar(select(func.coalesce(func.sum(signed), 0)).where(CashTransaction.invoice_id == inv.id)) or Decimal(0)


def invoice_out(db, inv) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv)
    out.lines = [LineOut.model_validate(l) for l in _lines(db, inv)]
    # payments of an order-based invoice are the order's payments (deposit included);
    # a payment against such an invoice is booked on the order too, so nothing is counted twice
    out.paid_amount = money(db.get(WorkOrder, inv.work_order_id).paid_amount if inv.work_order_id else _paid(db, inv))
    out.balance = money(inv.total - out.paid_amount) if inv.status != "cancelled" else Decimal(0)
    return out


def _price(line: InvoiceLine) -> None:
    if line.discount_pct is None:
        line.discount_pct = Decimal(0)
    gross = Decimal(line.qty) * Decimal(line.unit_price)
    line.discount_amount = money(gross * Decimal(line.discount_pct) / 100)
    line.line_total = money(gross - line.discount_amount)


def _totals(db, inv: Invoice) -> None:
    lines = _lines(db, inv)
    inv.lines_total = money(sum((l.line_total for l in lines), Decimal(0)))
    inv.lines_discount = money(sum((l.discount_amount for l in lines), Decimal(0)))
    if inv.discount_amount > inv.lines_total:
        raise ValidationFailed("Discount larger than the invoice", code="DISCOUNT_TOO_LARGE")
    taxable = inv.lines_total - inv.discount_amount
    inv.tax_amount = money(taxable * inv.tax_pct / 100)
    inv.total = money(taxable + inv.tax_amount)
    inv.updated_at = utcnow()


def _line_from_calc(position, *, location, model_id, opening_w, opening_h, color, glass, params, qty, unit_price,
                    calc, db) -> InvoiceLine:
    model = db.get(ProductModel, model_id)
    inputs = (calc or {}).get("inputs", {})
    line = InvoiceLine(position=position, kind="product", location=location, model_id=model_id,
                       model_name=model.name if model else "", model_image_id=model_image(model, color),
                       description=model.name if model else "", opening_width_mm=opening_w,
                       opening_height_mm=opening_h,
                       width_mm=Decimal(inputs["width_mm"]) if inputs.get("width_mm") else None,
                       height_mm=Decimal(inputs["height_mm"]) if inputs.get("height_mm") else None,
                       color_code=color, glass_material_code=glass, params=params or {},
                       drawing=(calc or {}).get("drawing", []), qty=Decimal(qty), unit_price=unit_price)
    _price(line)
    return line


def _get(db, ctx, inv_id, perm=READ_PERM) -> Invoice:
    inv = get_or_404(db, Invoice, inv_id)
    ctx.require(perm, inv.branch_id)
    return inv


def _require_draft(inv: Invoice) -> None:
    if inv.status != "draft":
        raise Conflict("Issued invoices cannot be changed", code="INVOICE_LOCKED")


@router.get("/invoices", response_model=Page[InvoiceOut])
def list_invoices(customer_id: uuid.UUID | None = None, status: str | None = None, params: PageParams = Depends(),
                  dc=Depends(require(READ_PERM))):
    db, ctx = dc
    stmt = select(Invoice).where(Invoice.deleted_at.is_(None)).order_by(Invoice.created_at.desc())
    stmt = branch_scope(stmt, ctx, READ_PERM, Invoice.branch_id)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    page = paginate(db, stmt, params, InvoiceOut)
    page["items"] = [invoice_out(db, db.get(Invoice, i.id)) for i in page["items"]]
    return page


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(body: InvoiceIn, dc=Depends(require("invoices.create"))):
    db, ctx = dc
    settings = get_company_settings(db, ctx.company_id)
    new_lines: list[InvoiceLine] = []
    customer_id, branch_id, quotation_id = body.customer_id, body.branch_id, body.quotation_id
    tax = body.tax_pct
    discount = body.discount_amount
    salesperson_id = body.salesperson_id
    if body.work_order_id:
        wo = get_or_404(db, WorkOrder, body.work_order_id)
        if wo.stage == "cancelled":
            raise Conflict("Work order is cancelled", code="WO_CANCELLED")
        if db.scalar(select(Invoice).where(Invoice.work_order_id == wo.id, Invoice.status != "cancelled",
                                           Invoice.deleted_at.is_(None))):
            raise Conflict("Work order already invoiced", code="ALREADY_INVOICED")
        customer_id, branch_id, quotation_id = wo.customer_id, wo.branch_id, wo.quotation_id
        salesperson_id = salesperson_id or wo.salesperson_id
        if wo.quotation_id:
            q = db.get(Quotation, wo.quotation_id)
            tax = tax if tax is not None else q.tax_pct
            discount = discount or q.discount_amount
        for item in db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id)
                               .order_by(WorkOrderItem.position)):
            new_lines.append(_line_from_calc(item.position, location=item.location, model_id=item.model_id,
                                             opening_w=item.opening_width_mm, opening_h=item.opening_height_mm,
                                             color=item.color_code, glass=item.glass_material_code,
                                             params=item.params, qty=item.qty, unit_price=item.unit_price,
                                             calc=item.calc, db=db))
    elif body.quotation_id:
        q = get_or_404(db, Quotation, body.quotation_id)
        if q.status != "accepted":
            raise Conflict("Quotation must be accepted", code="QUOTE_NOT_ACCEPTED")
        customer_id, branch_id = q.customer_id, q.branch_id
        salesperson_id = salesperson_id or q.salesperson_id
        tax = tax if tax is not None else q.tax_pct
        discount = discount or q.discount_amount
        for l in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)
                            .order_by(QuotationLine.position, QuotationLine.parent_line_id.is_not(None))):
            new_lines.append(_line_from_calc(l.position, location=l.location, model_id=l.model_id,
                                             opening_w=l.opening_width_mm, opening_h=l.opening_height_mm,
                                             color=l.color_code, glass=l.glass_material_code, params=l.params,
                                             qty=l.qty, unit_price=l.unit_price, calc=l.calc, db=db))
    if customer_id is None or branch_id is None:
        raise ValidationFailed("customer_id and branch_id required", code="CUSTOMER_REQUIRED")
    ctx.require("invoices.create", branch_id)
    get_or_404(db, Customer, customer_id)
    get_or_404(db, Branch, branch_id)
    inv = Invoice(customer_id=customer_id, branch_id=branch_id, work_order_id=body.work_order_id,
                  quotation_id=quotation_id, discount_amount=discount,
                  tax_pct=tax if tax is not None else settings.default_tax_pct,
                  due_date=date.today() + timedelta(days=body.due_days) if body.due_days else None,
                  notes=body.notes, terms=body.terms if body.terms is not None else settings.quote_terms,
                  salesperson_id=salesperson_for(db, ctx, salesperson_id))
    db.add(inv)
    db.flush()
    for i, l in enumerate(new_lines, 1):
        l.invoice_id, l.position = inv.id, i
        db.add(l)
    for l in body.lines:
        db.add(_manual_line(db, inv, l, len(new_lines) + body.lines.index(l) + 1))
    db.flush()
    _totals(db, inv)
    audit(db, inv, "create")
    db.commit()
    return invoice_out(db, inv)


def _manual_line(db, inv, l: LineIn, position: int) -> InvoiceLine:
    model = db.get(ProductModel, l.model_id) if l.model_id else None
    line = InvoiceLine(invoice_id=inv.id, position=position, kind=l.kind, description=l.description or
                       (model.name if model else ""), location=l.location, model_id=l.model_id,
                       model_name=model.name if model else "", model_image_id=model_image(model, l.color_code),
                       opening_width_mm=l.opening_width_mm, opening_height_mm=l.opening_height_mm,
                       color_code=l.color_code, glass_material_code=l.glass_material_code, qty=l.qty,
                       unit_price=l.unit_price, discount_pct=l.discount_pct)
    _price(line)
    return line


@router.get("/invoices/{inv_id}", response_model=InvoiceOut)
def get_invoice(inv_id: uuid.UUID, dc=Depends(require(READ_PERM))):
    db, ctx = dc
    return invoice_out(db, _get(db, ctx, inv_id))


@router.patch("/invoices/{inv_id}", response_model=InvoiceOut)
def update_invoice(inv_id: uuid.UUID, body: InvoiceUpdate, dc=Depends(require(EDIT_PERM))):
    db, ctx = dc
    inv = _get(db, ctx, inv_id, EDIT_PERM)
    check_version(inv, body.version)
    _require_draft(inv)
    before = snapshot(inv)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("salesperson_id"):
        salesperson_for(db, ctx, data["salesperson_id"])
    apply_changes(inv, data)
    _totals(db, inv)
    audit(db, inv, "update", before)
    db.commit()
    return invoice_out(db, inv)


@router.post("/invoices/{inv_id}/lines", response_model=InvoiceOut, status_code=201)
def add_line(inv_id: uuid.UUID, body: LineIn, dc=Depends(require(EDIT_PERM))):
    db, ctx = dc
    inv = _get(db, ctx, inv_id, EDIT_PERM)
    _require_draft(inv)
    db.add(_manual_line(db, inv, body, len(_lines(db, inv)) + 1))
    db.flush()
    _totals(db, inv)
    db.commit()
    return invoice_out(db, inv)


@router.patch("/invoice-lines/{line_id}", response_model=InvoiceOut)
def update_line(line_id: uuid.UUID, body: LineUpdate, dc=Depends(require(EDIT_PERM))):
    db, ctx = dc
    line = get_or_404(db, InvoiceLine, line_id)
    inv = _get(db, ctx, line.invoice_id, EDIT_PERM)
    _require_draft(inv)
    check_version(line, body.version)
    before = snapshot(line)
    apply_changes(line, body.model_dump(exclude_unset=True, exclude={"version"}))
    _price(line)
    db.flush()
    _totals(db, inv)
    audit(db, line, "update", before)
    db.commit()
    return invoice_out(db, inv)


@router.delete("/invoice-lines/{line_id}", response_model=InvoiceOut)
def delete_line(line_id: uuid.UUID, dc=Depends(require(EDIT_PERM))):
    db, ctx = dc
    line = get_or_404(db, InvoiceLine, line_id)
    inv = _get(db, ctx, line.invoice_id, EDIT_PERM)
    _require_draft(inv)
    db.delete(line)
    db.flush()
    _totals(db, inv)
    db.commit()
    return invoice_out(db, inv)


class VersionIn(BaseModel):
    version: int


@router.post("/invoices/{inv_id}/issue", response_model=InvoiceOut)
def issue(inv_id: uuid.UUID, body: VersionIn, dc=Depends(require(EDIT_PERM))):
    """Give the invoice its sequential number and lock it."""
    db, ctx = dc
    inv = _get(db, ctx, inv_id, EDIT_PERM)
    check_version(inv, body.version)
    _require_draft(inv)
    if not _lines(db, inv):
        raise ValidationFailed("Invoice has no lines", code="INVOICE_EMPTY")
    before = snapshot(inv)
    branch = db.get(Branch, inv.branch_id)
    inv.number = next_number(db, "invoice", "INV", branch.code)
    inv.status, inv.issue_date = "issued", date.today()
    audit(db, inv, "update", before, note="issued")
    from app.modules.notifications.router import alert, customer_name
    alert(db, ctx, "sales", inv.branch_id, f"فاتورة صادرة {inv.number} بـ {inv.total}", customer_name(db, inv.customer_id),
          f"invoices/{inv.id}")
    db.commit()
    return invoice_out(db, inv)


class CancelIn(BaseModel):
    version: int
    reason: str = Field(min_length=3)


@router.post("/invoices/{inv_id}/cancel", response_model=InvoiceOut)
def cancel(inv_id: uuid.UUID, body: CancelIn, dc=Depends(require("invoices.delete"))):
    db, ctx = dc
    inv = _get(db, ctx, inv_id, "invoices.delete")
    check_version(inv, body.version)
    if inv.status == "cancelled":
        raise Conflict("Already cancelled", code="INVALID_TRANSITION")
    before = snapshot(inv)
    inv.status, inv.cancelled_at, inv.cancel_reason = "cancelled", utcnow(), body.reason
    audit(db, inv, "update", before, note=f"cancelled: {body.reason}")
    db.commit()
    return invoice_out(db, inv)


@deletable(router, "/invoices/{inv_id}", "invoices", ("الفاتورة", Invoice, "number"))
def delete_invoice(inv_id: uuid.UUID, dc=Depends(require("invoices.delete"))):
    """A draft is deleted; an issued invoice keeps its number and is cancelled with a reason instead."""
    db, ctx = dc
    inv = _get(db, ctx, inv_id, "invoices.delete")
    if inv.status != "draft":
        raise Conflict("Issued invoices are cancelled, not deleted", code="INVOICE_ISSUED")
    before = snapshot(inv)
    inv.deleted_at = utcnow()
    audit(db, inv, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")
