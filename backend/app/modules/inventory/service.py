from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.inventory.models import StockBalance, StockMovement, Warehouse
from app.modules.library.models import Material, MaterialVariant


def resolve_sku(db: Session, sku: str) -> tuple[Material, str]:
    """SKU -> (material, unit). Accepts a colour variant SKU or a material code."""
    variant = db.scalar(select(MaterialVariant).where(MaterialVariant.sku == sku))
    material = db.get(Material, variant.material_id) if variant else None
    if material is None:
        from app.modules.library.service import find_material
        material = find_material(db, sku)
    if material is None:
        raise ValidationFailed(f"Unknown SKU {sku}", code="UNKNOWN_SKU", details={"sku": sku})
    return material, material.unit


def move(db: Session, ctx, *, warehouse_id: uuid.UUID, sku: str, qty: Decimal, kind: str,
         unit_cost: Decimal | None = None, ref_type: str | None = None, ref_id: uuid.UUID | None = None,
         note: str = "", allow_negative: bool = False) -> StockMovement:
    qty = Decimal(qty)
    if qty == 0:
        raise ValidationFailed("Quantity cannot be zero", code="QTY_ZERO")
    material, unit = resolve_sku(db, sku)
    balance = db.scalar(select(StockBalance).where(StockBalance.warehouse_id == warehouse_id,
                                                   StockBalance.sku == sku).with_for_update())
    if balance is None:
        balance = StockBalance(warehouse_id=warehouse_id, sku=sku, material_id=material.id, unit=unit, qty=Decimal(0))
        db.add(balance)
        db.flush()
        balance = db.scalar(select(StockBalance).where(StockBalance.id == balance.id).with_for_update())
    new_qty = balance.qty + qty
    if new_qty < 0 and not allow_negative:
        raise Conflict(f"Insufficient stock for {sku}", code="INSUFFICIENT_STOCK",
                       details={"sku": sku, "available": str(balance.qty), "requested": str(-qty)})
    if qty > 0 and unit_cost is not None:
        old_value = (balance.avg_cost or Decimal(0)) * max(balance.qty, Decimal(0))
        balance.avg_cost = ((old_value + unit_cost * qty) / (max(balance.qty, Decimal(0)) + qty)).quantize(Decimal("0.0001"))
    balance.qty = new_qty
    m = StockMovement(warehouse_id=warehouse_id, sku=sku, material_id=material.id, qty=qty, unit=unit,
                      unit_cost=unit_cost if unit_cost is not None else balance.avg_cost, kind=kind,
                      ref_type=ref_type, ref_id=ref_id, user_id=ctx.user_id, note=note)
    db.add(m)
    return m


def get_warehouse(db: Session, ctx, warehouse_id: uuid.UUID, permission: str) -> Warehouse:
    wh = db.get(Warehouse, warehouse_id)
    if wh is None:
        raise NotFound("Warehouse not found")
    ctx.require(permission, wh.branch_id)
    return wh


def issue_for_work_order(db: Session, ctx, wo) -> None:
    """Deduct the materials a work order consumes (whole bars for profiles,
    accessories by quantity) from the order's warehouse. All or nothing."""
    if not wo.outputs:
        raise Conflict("Generate manufacturing outputs first", code="NO_OUTPUTS")
    if wo.warehouse_id is None:
        raise ValidationFailed("Work order has no warehouse", code="NO_WAREHOUSE")
    get_warehouse(db, ctx, wo.warehouse_id, "workorders.stage")
    for c in wo.outputs.get("costs", []):
        if c["type"] == "glass":
            continue  # glass is usually cut to size by the supplier per order
        move(db, ctx, warehouse_id=wo.warehouse_id, sku=c["sku"], qty=-Decimal(c["qty"]), kind="issue",
             ref_type="work_order", ref_id=wo.id, note=wo.number)
    # materials without a price are not in "costs" but are still consumed
    priced = {c["sku"] for c in wo.outputs.get("costs", [])}
    for a in wo.outputs.get("accessories", []):
        if a["sku"] not in priced:
            move(db, ctx, warehouse_id=wo.warehouse_id, sku=a["sku"], qty=-Decimal(a["qty"]), kind="issue",
                 ref_type="work_order", ref_id=wo.id, note=wo.number)
    for plan in wo.outputs.get("optimisation", []):
        if plan["sku"] not in priced:
            move(db, ctx, warehouse_id=wo.warehouse_id, sku=plan["sku"],
                 qty=-Decimal(plan["total_length_mm"]) / 1000, kind="issue", ref_type="work_order", ref_id=wo.id,
                 note=wo.number)
    wo.materials_issued = True
