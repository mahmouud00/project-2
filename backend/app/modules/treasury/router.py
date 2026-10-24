from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.api.common import ORMModel, Page, PageParams, Record, paginate
from app.core.audit import audit
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.modules.crm.models import Customer
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.org.models import Branch
from app.modules.production.models import WorkOrder
from app.modules.purchasing.models import PurchaseOrder, Supplier
from app.modules.treasury.models import Cashbox, CashTransaction
from app.tenancy.context import require

router = APIRouter(tags=["treasury"])


class CashboxIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str
    branch_id: uuid.UUID


class CashboxOut(Record):
    code: str
    name: str
    branch_id: uuid.UUID
    is_active: bool
    balance: Decimal = Decimal(0)


def _balance(db, cashbox_id) -> Decimal:
    signed = case((CashTransaction.direction == "in", CashTransaction.amount), else_=-CashTransaction.amount)
    return db.scalar(select(func.coalesce(func.sum(signed), 0)).where(CashTransaction.cashbox_id == cashbox_id))


@router.get("/cashboxes", response_model=list[CashboxOut])
def list_cashboxes(dc=Depends(require("treasury.read"))):
    db, ctx = dc
    out = []
    for c in db.scalars(branch_scope(select(Cashbox).order_by(Cashbox.code), ctx, "treasury.read", Cashbox.branch_id)):
        o = CashboxOut.model_validate(c)
        o.balance = _balance(db, c.id)
        out.append(o)
    return out


@router.post("/cashboxes", response_model=CashboxOut, status_code=201)
def create_cashbox(body: CashboxIn, dc=Depends(require("org.manage"))):
    db, _ = dc
    get_or_404(db, Branch, body.branch_id)
    if db.scalar(select(Cashbox).where(Cashbox.code == body.code)):
        raise Conflict("Cashbox code exists", code="DUPLICATE_CODE")
    c = Cashbox(**body.model_dump())
    db.add(c)
    db.flush()
    audit(db, c, "create")
    db.commit()
    return c


class TxIn(BaseModel):
    cashbox_id: uuid.UUID
    direction: str = Field(pattern="^(in|out)$")
    amount: Decimal = Field(gt=0)
    method: str = Field("cash", pattern="^(cash|transfer|cheque|card)$")
    party_type: str = Field(pattern="^(customer|supplier|other)$")
    party_id: uuid.UUID | None = None
    work_order_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    reference: str = ""
    note: str = ""


class TxOut(ORMModel):
    id: uuid.UUID
    number: str
    at: datetime
    cashbox_id: uuid.UUID
    direction: str
    amount: Decimal
    method: str
    party_type: str
    party_id: uuid.UUID | None
    work_order_id: uuid.UUID | None
    purchase_order_id: uuid.UUID | None
    reference: str
    note: str
    reverses_id: uuid.UUID | None
    reversed: bool


def _apply_links(db, tx: CashTransaction, sign: int) -> None:
    amount = tx.amount * sign
    if tx.work_order_id:
        wo = db.get(WorkOrder, tx.work_order_id)
        wo.paid_amount += amount if tx.direction == "in" else -amount
    if tx.purchase_order_id:
        po = db.get(PurchaseOrder, tx.purchase_order_id)
        po.paid_amount += amount if tx.direction == "out" else -amount


@router.post("/cash-transactions", response_model=TxOut, status_code=201)
def create_tx(body: TxIn, dc=Depends(require("treasury.write"))):
    db, ctx = dc
    box = get_or_404(db, Cashbox, body.cashbox_id)
    ctx.require("treasury.write", box.branch_id)
    if body.party_type == "customer":
        if body.party_id is None:
            raise ValidationFailed("Customer required", code="PARTY_REQUIRED")
        get_or_404(db, Customer, body.party_id)
    if body.party_type == "supplier":
        if body.party_id is None:
            raise ValidationFailed("Supplier required", code="PARTY_REQUIRED")
        get_or_404(db, Supplier, body.party_id)
    if body.work_order_id:
        wo = get_or_404(db, WorkOrder, body.work_order_id)
        if body.party_type != "customer" or wo.customer_id != body.party_id:
            raise ValidationFailed("Work order belongs to another customer", code="PARTY_MISMATCH")
    if body.purchase_order_id:
        po = get_or_404(db, PurchaseOrder, body.purchase_order_id)
        if body.party_type != "supplier" or po.supplier_id != body.party_id:
            raise ValidationFailed("Purchase order belongs to another supplier", code="PARTY_MISMATCH")
    if body.direction == "out" and _balance(db, box.id) < body.amount and body.method == "cash":
        raise Conflict("Not enough cash in the cashbox", code="INSUFFICIENT_CASH")
    branch = db.get(Branch, box.branch_id)
    tx = CashTransaction(number=next_number(db, "cash", "CR" if body.direction == "in" else "CP", branch.code),
                         user_id=ctx.user_id, **body.model_dump())
    db.add(tx)
    db.flush()
    _apply_links(db, tx, 1)
    audit(db, tx, "create")
    db.commit()
    return tx


class ReverseIn(BaseModel):
    note: str = Field(min_length=1)


@router.post("/cash-transactions/{tx_id}/reverse", response_model=TxOut, status_code=201)
def reverse_tx(tx_id: uuid.UUID, body: ReverseIn, dc=Depends(require("treasury.write"))):
    db, ctx = dc
    tx = db.scalar(select(CashTransaction).where(CashTransaction.id == tx_id).with_for_update())
    if tx is None:
        from app.core.errors import NotFound
        raise NotFound("Transaction not found")
    box = db.get(Cashbox, tx.cashbox_id)
    ctx.require("treasury.write", box.branch_id)
    if tx.reversed or tx.reverses_id:
        raise Conflict("Already reversed", code="ALREADY_REVERSED")
    branch = db.get(Branch, box.branch_id)
    rev = CashTransaction(number=next_number(db, "cash", "RV", branch.code), cashbox_id=tx.cashbox_id,
                          direction="out" if tx.direction == "in" else "in", amount=tx.amount, method=tx.method,
                          party_type=tx.party_type, party_id=tx.party_id, reference=tx.reference,
                          note=body.note, user_id=ctx.user_id, reverses_id=tx.id)
    db.add(rev)
    tx.reversed = True
    _apply_links(db, tx, -1)
    db.flush()
    audit(db, rev, "create", note=f"reverses {tx.number}")
    db.commit()
    return rev


@router.get("/cash-transactions", response_model=Page[TxOut])
def list_tx(cashbox_id: uuid.UUID | None = None, party_id: uuid.UUID | None = None,
            work_order_id: uuid.UUID | None = None, params: PageParams = Depends(),
            dc=Depends(require("treasury.read"))):
    db, ctx = dc
    stmt = select(CashTransaction).order_by(CashTransaction.at.desc())
    branches = ctx.branches_for("treasury.read")
    if branches is not None:
        stmt = stmt.join(Cashbox, Cashbox.id == CashTransaction.cashbox_id).where(Cashbox.branch_id.in_(branches))
    if cashbox_id:
        stmt = stmt.where(CashTransaction.cashbox_id == cashbox_id)
    if party_id:
        stmt = stmt.where(CashTransaction.party_id == party_id)
    if work_order_id:
        stmt = stmt.where(CashTransaction.work_order_id == work_order_id)
    return paginate(db, stmt, params, TxOut)


@router.get("/customers/{customer_id}/statement")
def customer_statement(customer_id: uuid.UUID, dc=Depends(require("treasury.read"))):
    db, _ = dc
    get_or_404(db, Customer, customer_id)
    orders = db.scalars(select(WorkOrder).where(WorkOrder.customer_id == customer_id, WorkOrder.deleted_at.is_(None),
                                                WorkOrder.stage != "cancelled")).all()
    signed = case((CashTransaction.direction == "in", CashTransaction.amount), else_=-CashTransaction.amount)
    paid = db.scalar(select(func.coalesce(func.sum(signed), 0)).where(
        CashTransaction.party_type == "customer", CashTransaction.party_id == customer_id))
    billed = sum((o.total for o in orders), Decimal(0))
    return {"customer_id": str(customer_id), "billed": str(billed), "paid": str(paid), "balance": str(billed - paid),
            "orders": [{"id": str(o.id), "number": o.number, "stage": o.stage, "total": str(o.total),
                        "paid": str(o.paid_amount)} for o in orders]}


@router.get("/suppliers/{supplier_id}/statement")
def supplier_statement(supplier_id: uuid.UUID, dc=Depends(require("treasury.read"))):
    db, _ = dc
    get_or_404(db, Supplier, supplier_id)
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier_id,
                                                 PurchaseOrder.deleted_at.is_(None))).all()
    signed = case((CashTransaction.direction == "out", CashTransaction.amount), else_=-CashTransaction.amount)
    paid = db.scalar(select(func.coalesce(func.sum(signed), 0)).where(
        CashTransaction.party_type == "supplier", CashTransaction.party_id == supplier_id))
    received = sum((p.received_value for p in pos), Decimal(0))
    return {"supplier_id": str(supplier_id), "received_value": str(received), "paid": str(paid),
            "balance": str(received - paid),
            "orders": [{"id": str(p.id), "number": p.number, "status": p.status, "total": str(p.total),
                        "received_value": str(p.received_value), "paid": str(p.paid_amount)} for p in pos]}
