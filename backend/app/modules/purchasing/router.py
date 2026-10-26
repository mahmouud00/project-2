from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import DeleteResult, ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import move, resolve_sku
from app.modules.library.models import CompanyMaterialSetting, MaterialVariant
from app.modules.org.models import Branch
from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier
from app.modules.sales.pricing import money
from app.tenancy.context import require

router = APIRouter(tags=["purchasing"])


class SupplierIn(BaseModel):
    code: str | None = Field(None, max_length=40)
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    tax_number: str | None = None
    notes: str = ""


class SupplierUpdate(VersionedUpdate):
    name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    tax_number: str | None = None
    notes: str | None = None


class SupplierOut(Record):
    code: str
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None
    address: str | None
    tax_number: str | None
    notes: str


@router.get("/suppliers", response_model=Page[SupplierOut])
def list_suppliers(params: PageParams = Depends(), dc=Depends(require("purchasing.read"))):
    db, _ = dc
    return paginate(db, select(Supplier).where(Supplier.deleted_at.is_(None)).order_by(Supplier.name), params,
                    SupplierOut)


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, dc=Depends(require("purchasing.create"))):
    db, _ = dc
    data = body.model_dump()
    data["code"] = data["code"] or next_number(db, "supplier", "SU")
    if db.scalar(select(Supplier).where(Supplier.code == data["code"])):
        raise Conflict("Supplier code exists", code="DUPLICATE_CODE")
    s = Supplier(**data)
    db.add(s)
    db.flush()
    audit(db, s, "create")
    db.commit()
    return s


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: uuid.UUID, body: SupplierUpdate, dc=Depends(require("purchasing.write"))):
    db, _ = dc
    s = get_or_404(db, Supplier, supplier_id)
    check_version(s, body.version)
    before = snapshot(s)
    apply_changes(s, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, s, "update", before)
    db.commit()
    return s


class POLineIn(BaseModel):
    sku: str
    qty: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)


class POIn(BaseModel):
    supplier_id: uuid.UUID
    branch_id: uuid.UUID
    warehouse_id: uuid.UUID
    order_date: date | None = None
    notes: str = ""
    lines: list[POLineIn] = Field(min_length=1)


class POLineOut(ORMModel):
    id: uuid.UUID
    position: int
    sku: str
    material_id: uuid.UUID
    qty: Decimal
    unit_cost: Decimal
    received_qty: Decimal


class POOut(Record):
    number: str
    supplier_id: uuid.UUID
    branch_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: str
    order_date: date | None
    total: Decimal
    received_value: Decimal
    paid_amount: Decimal
    notes: str
    lines: list[POLineOut] = []


def _po_out(db, po) -> POOut:
    out = POOut.model_validate(po)
    out.lines = [POLineOut.model_validate(l) for l in db.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id).order_by(PurchaseOrderLine.position))]
    return out


def _get_po(db, ctx, po_id, permission) -> PurchaseOrder:
    po = get_or_404(db, PurchaseOrder, po_id)
    ctx.require(permission, po.branch_id)
    return po


@router.get("/purchase-orders", response_model=Page[POOut])
def list_pos(status: str | None = None, supplier_id: uuid.UUID | None = None, params: PageParams = Depends(),
             dc=Depends(require("purchasing.read"))):
    db, ctx = dc
    stmt = select(PurchaseOrder).where(PurchaseOrder.deleted_at.is_(None)).order_by(PurchaseOrder.created_at.desc())
    stmt = branch_scope(stmt, ctx, "purchasing.read", PurchaseOrder.branch_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    return paginate(db, stmt, params, POOut)


@router.get("/purchase-orders/{po_id}", response_model=POOut)
def get_po(po_id: uuid.UUID, dc=Depends(require("purchasing.read"))):
    db, ctx = dc
    return _po_out(db, _get_po(db, ctx, po_id, "purchasing.read"))


@router.post("/purchase-orders", response_model=POOut, status_code=201)
def create_po(body: POIn, dc=Depends(require("purchasing.create"))):
    db, ctx = dc
    ctx.require("purchasing.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    get_or_404(db, Supplier, body.supplier_id)
    wh = get_or_404(db, Warehouse, body.warehouse_id)
    if wh.branch_id != branch.id:
        raise ValidationFailed("Warehouse belongs to another branch", code="WAREHOUSE_BRANCH")
    po = PurchaseOrder(number=next_number(db, "po", "PO", branch.code), order_date=body.order_date or date.today(),
                       **body.model_dump(exclude={"lines", "order_date"}))
    db.add(po)
    db.flush()
    total = Decimal(0)
    for i, l in enumerate(body.lines, 1):
        material, _ = resolve_sku(db, l.sku)
        db.add(PurchaseOrderLine(purchase_order_id=po.id, position=i, sku=l.sku, material_id=material.id, qty=l.qty,
                                 unit_cost=l.unit_cost))
        total += l.qty * l.unit_cost
    po.total = money(total)
    audit(db, po, "create")
    db.commit()
    return _po_out(db, po)


class POStatusIn(BaseModel):
    version: int
    status: str = Field(pattern="^(ordered|cancelled)$")


@router.post("/purchase-orders/{po_id}/status", response_model=POOut)
def po_status(po_id: uuid.UUID, body: POStatusIn, dc=Depends(require("purchasing.write"))):
    db, ctx = dc
    po = _get_po(db, ctx, po_id, "purchasing.write")
    check_version(po, body.version)
    allowed = {"draft": {"ordered", "cancelled"}, "ordered": {"cancelled"}}
    if body.status not in allowed.get(po.status, set()) or (body.status == "cancelled" and po.received_value > 0):
        raise Conflict(f"Cannot go from {po.status} to {body.status}", code="INVALID_TRANSITION")
    before = snapshot(po)
    po.status = body.status
    audit(db, po, "update", before)
    db.commit()
    return _po_out(db, po)


class ReceiveLine(BaseModel):
    line_id: uuid.UUID
    qty: Decimal = Field(gt=0)


class ReceiveIn(BaseModel):
    version: int
    lines: list[ReceiveLine] = Field(min_length=1)
    update_company_cost: bool = True  # last purchase price becomes the company's unit cost


@router.post("/purchase-orders/{po_id}/receive", response_model=POOut)
def receive(po_id: uuid.UUID, body: ReceiveIn, dc=Depends(require("inventory.write"))):
    db, ctx = dc
    po = _get_po(db, ctx, po_id, "inventory.write")
    check_version(po, body.version)
    if po.status not in ("ordered", "partial"):
        raise Conflict("Order is not open for receiving", code="INVALID_TRANSITION")
    for r in body.lines:
        line = get_or_404(db, PurchaseOrderLine, r.line_id)
        if line.purchase_order_id != po.id:
            raise ValidationFailed("Line does not belong to this order", code="LINE_MISMATCH")
        if line.received_qty + r.qty > line.qty:
            raise ValidationFailed("Receiving more than ordered", code="OVER_RECEIPT",
                                   details={"sku": line.sku, "remaining": str(line.qty - line.received_qty)})
        move(db, ctx, warehouse_id=po.warehouse_id, sku=line.sku, qty=r.qty, kind="receipt", unit_cost=line.unit_cost,
             ref_type="purchase_order", ref_id=po.id, note=po.number)
        line.received_qty += r.qty
        po.received_value = money(po.received_value + r.qty * line.unit_cost)
        if body.update_company_cost:
            variant = db.scalar(select(MaterialVariant).where(MaterialVariant.sku == line.sku))
            color = variant.color_code if variant else ""
            setting = db.scalar(select(CompanyMaterialSetting).where(
                CompanyMaterialSetting.material_id == line.material_id, CompanyMaterialSetting.color_code == color))
            if setting is None:
                db.add(CompanyMaterialSetting(material_id=line.material_id, color_code=color, unit_cost=line.unit_cost))
            else:
                setting.unit_cost = line.unit_cost
    db.flush()
    lines = list(db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id)))
    po.status = "received" if all(l.received_qty >= l.qty for l in lines) else "partial"
    db.commit()
    return _po_out(db, po)


@router.delete("/suppliers/{supplier_id}", response_model=DeleteResult)
def delete_supplier(supplier_id: uuid.UUID, dc=Depends(require("purchasing.delete"))):
    db, _ = dc
    supplier = get_or_404(db, Supplier, supplier_id)
    before = snapshot(supplier)
    supplier.deleted_at = utcnow()
    audit(db, supplier, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


@router.delete("/purchase-orders/{po_id}", response_model=DeleteResult)
def delete_po(po_id: uuid.UUID, dc=Depends(require("purchasing.delete"))):
    """A draft order is deleted; an ordered one is cancelled instead (status "cancelled")."""
    db, ctx = dc
    po = _get_po(db, ctx, po_id, "purchasing.delete")
    if po.status != "draft":
        raise Conflict("Only a draft purchase order can be deleted", code="PO_NOT_DRAFT")
    before = snapshot(po)
    po.deleted_at = utcnow()
    audit(db, po, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")
