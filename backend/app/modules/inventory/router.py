from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.inventory.models import StockBalance, StockMovement, StockTransfer, Warehouse
from app.modules.inventory.service import get_warehouse, issue_for_work_order, move
from app.modules.org.models import Branch
from app.tenancy.context import require

router = APIRouter(tags=["inventory"])


class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str
    branch_id: uuid.UUID


class WarehouseUpdate(VersionedUpdate):
    name: str | None = None
    is_active: bool | None = None


class WarehouseOut(Record):
    code: str
    name: str
    branch_id: uuid.UUID
    is_active: bool


@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(dc=Depends(require("inventory.read"))):
    db, ctx = dc
    stmt = branch_scope(select(Warehouse).order_by(Warehouse.code), ctx, "inventory.read", Warehouse.branch_id)
    return db.scalars(stmt).all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(body: WarehouseIn, dc=Depends(require("org.manage"))):
    db, _ = dc
    get_or_404(db, Branch, body.branch_id)
    if db.scalar(select(Warehouse).where(Warehouse.code == body.code)):
        raise Conflict("Warehouse code exists", code="DUPLICATE_CODE")
    wh = Warehouse(**body.model_dump())
    db.add(wh)
    db.flush()
    audit(db, wh, "create")
    db.commit()
    return wh


@router.patch("/warehouses/{wh_id}", response_model=WarehouseOut)
def update_warehouse(wh_id: uuid.UUID, body: WarehouseUpdate, dc=Depends(require("org.manage"))):
    db, _ = dc
    wh = get_or_404(db, Warehouse, wh_id)
    check_version(wh, body.version)
    before = snapshot(wh)
    apply_changes(wh, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, wh, "update", before)
    db.commit()
    return wh


class BalanceOut(ORMModel):
    warehouse_id: uuid.UUID
    sku: str
    material_id: uuid.UUID | None
    unit: str
    qty: Decimal
    avg_cost: Decimal | None


@router.get("/inventory/balances", response_model=list[BalanceOut])
def balances(warehouse_id: uuid.UUID, sku: str | None = None, dc=Depends(require("inventory.read"))):
    db, ctx = dc
    get_warehouse(db, ctx, warehouse_id, "inventory.read")
    stmt = select(StockBalance).where(StockBalance.warehouse_id == warehouse_id).order_by(StockBalance.sku)
    if sku:
        stmt = stmt.where(StockBalance.sku == sku)
    return db.scalars(stmt).all()


class MovementOut(ORMModel):
    id: uuid.UUID
    at: datetime
    warehouse_id: uuid.UUID
    sku: str
    qty: Decimal
    unit: str
    unit_cost: Decimal | None
    kind: str
    ref_type: str | None
    ref_id: uuid.UUID | None
    note: str


@router.get("/inventory/movements", response_model=Page[MovementOut])
def movements(warehouse_id: uuid.UUID, sku: str | None = None, ref_id: uuid.UUID | None = None,
              params: PageParams = Depends(), dc=Depends(require("inventory.read"))):
    db, ctx = dc
    get_warehouse(db, ctx, warehouse_id, "inventory.read")
    stmt = select(StockMovement).where(StockMovement.warehouse_id == warehouse_id).order_by(StockMovement.at.desc())
    if sku:
        stmt = stmt.where(StockMovement.sku == sku)
    if ref_id:
        stmt = stmt.where(StockMovement.ref_id == ref_id)
    return paginate(db, stmt, params, MovementOut)


class AdjustLine(BaseModel):
    sku: str
    qty: Decimal  # + add / - remove
    unit_cost: Decimal | None = Field(None, ge=0)
    note: str = ""


class AdjustIn(BaseModel):
    warehouse_id: uuid.UUID
    reason: str = Field(min_length=1)
    lines: list[AdjustLine] = Field(min_length=1)


@router.post("/inventory/adjustments", status_code=201)
def adjust(body: AdjustIn, dc=Depends(require("inventory.write"))):
    """Opening balance / stock count corrections."""
    db, ctx = dc
    get_warehouse(db, ctx, body.warehouse_id, "inventory.write")
    ref = uuid.uuid4()
    for line in body.lines:
        move(db, ctx, warehouse_id=body.warehouse_id, sku=line.sku, qty=line.qty, kind="adjustment",
             unit_cost=line.unit_cost, ref_type="adjustment", ref_id=ref, note=f"{body.reason} {line.note}".strip())
    db.commit()
    return {"ref_id": str(ref), "lines": len(body.lines)}


# ---------------------------------------------------------------- transfers
class TransferLine(BaseModel):
    sku: str
    qty: Decimal = Field(gt=0)


class TransferIn(BaseModel):
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    lines: list[TransferLine] = Field(min_length=1)
    note: str = ""


class TransferOut(Record):
    number: str
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    status: str
    lines: list
    note: str
    sent_at: datetime | None
    received_at: datetime | None


@router.post("/inventory/transfers", response_model=TransferOut, status_code=201)
def create_transfer(body: TransferIn, dc=Depends(require("inventory.write"))):
    db, ctx = dc
    if body.from_warehouse_id == body.to_warehouse_id:
        raise ValidationFailed("Same warehouse", code="SAME_WAREHOUSE")
    get_warehouse(db, ctx, body.from_warehouse_id, "inventory.write")
    get_or_404(db, Warehouse, body.to_warehouse_id)
    t = StockTransfer(number=next_number(db, "transfer", "TR"), from_warehouse_id=body.from_warehouse_id,
                      to_warehouse_id=body.to_warehouse_id, lines=[l.model_dump(mode="json") for l in body.lines],
                      note=body.note)
    db.add(t)
    db.flush()
    audit(db, t, "create")
    db.commit()
    return t


class VersionIn(BaseModel):
    version: int


@router.post("/inventory/transfers/{t_id}/send", response_model=TransferOut)
def send_transfer(t_id: uuid.UUID, body: VersionIn, dc=Depends(require("inventory.write"))):
    db, ctx = dc
    t = get_or_404(db, StockTransfer, t_id)
    get_warehouse(db, ctx, t.from_warehouse_id, "inventory.write")
    check_version(t, body.version)
    if t.status != "draft":
        raise Conflict("Transfer already sent", code="INVALID_TRANSITION")
    for line in t.lines:
        move(db, ctx, warehouse_id=t.from_warehouse_id, sku=line["sku"], qty=-Decimal(line["qty"]),
             kind="transfer_out", ref_type="transfer", ref_id=t.id, note=t.number)
    t.status, t.sent_at = "sent", utcnow()
    db.commit()
    return t


@router.post("/inventory/transfers/{t_id}/receive", response_model=TransferOut)
def receive_transfer(t_id: uuid.UUID, body: VersionIn, dc=Depends(require("inventory.write"))):
    db, ctx = dc
    t = get_or_404(db, StockTransfer, t_id)
    get_warehouse(db, ctx, t.to_warehouse_id, "inventory.write")
    check_version(t, body.version)
    if t.status != "sent":
        raise Conflict("Transfer not in transit", code="INVALID_TRANSITION")
    out_costs = {m.sku: m.unit_cost for m in db.scalars(select(StockMovement).where(
        StockMovement.ref_id == t.id, StockMovement.kind == "transfer_out"))}
    for line in t.lines:
        move(db, ctx, warehouse_id=t.to_warehouse_id, sku=line["sku"], qty=Decimal(line["qty"]), kind="transfer_in",
             unit_cost=out_costs.get(line["sku"]), ref_type="transfer", ref_id=t.id, note=t.number)
    t.status, t.received_at = "received", utcnow()
    db.commit()
    return t


@router.get("/inventory/transfers", response_model=list[TransferOut])
def list_transfers(status: str | None = None, dc=Depends(require("inventory.read"))):
    db, _ = dc
    stmt = select(StockTransfer).order_by(StockTransfer.created_at.desc())
    if status:
        stmt = stmt.where(StockTransfer.status == status)
    return db.scalars(stmt).all()


@router.post("/work-orders/{wo_id}/issue-materials")
def issue_materials(wo_id: uuid.UUID, dc=Depends(require("workorders.stage"))):
    """Deduct the order's materials from its warehouse (also done automatically
    when the order enters manufacturing with a warehouse set)."""
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    wo = get_or_404(db, WorkOrder, wo_id)
    ctx.require("workorders.stage", wo.branch_id)
    if wo.materials_issued:
        raise Conflict("Materials already issued", code="MATERIALS_ISSUED")
    issue_for_work_order(db, ctx, wo)
    db.commit()
    return {"status": "issued"}
