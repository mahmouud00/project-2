from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import DeleteResult, ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.models import Customer
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.org.models import Branch
from app.modules.org.settings import get_company_settings
from app.modules.production.manufacturing import generate_outputs
from app.modules.production.models import STAGE_NAMES, STAGES, WorkOrder, WorkOrderItem, WorkOrderStageLog
from app.modules.sales.models import Quotation, QuotationLine
from app.modules.sales.pricing import money
from app.tenancy.context import require

router = APIRouter(tags=["production"])

FROZEN_STAGES = ("manufacturing", "assembly", "quality", "delivered")


class WorkOrderIn(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    due_date: date | None = None
    notes: str = ""
    salesperson_id: uuid.UUID | None = None


class FromQuotationIn(BaseModel):
    quotation_id: uuid.UUID
    work_order_id: uuid.UUID | None = None  # attach to an order opened at survey stage
    due_date: date | None = None
    deposit_required: Decimal | None = Field(None, ge=0)


class WorkOrderUpdate(VersionedUpdate):
    due_date: date | None = None
    notes: str | None = None
    deposit_required: Decimal | None = Field(None, ge=0)
    salesperson_id: uuid.UUID | None = None


class ItemOut(ORMModel):
    id: uuid.UUID
    position: int
    location: str
    model_id: uuid.UUID
    formula_set_version_id: uuid.UUID
    opening_width_mm: Decimal
    opening_height_mm: Decimal
    params: dict
    color_code: str | None
    glass_material_code: str | None
    qty: int
    unit_price: Decimal


class StageLogOut(ORMModel):
    from_stage: str | None
    to_stage: str
    at: object
    user_id: uuid.UUID | None
    note: str


class WorkOrderOut(Record):
    number: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    quotation_id: uuid.UUID | None
    salesperson_id: uuid.UUID | None = None
    stage: str
    stage_name: str = ""
    total: Decimal
    deposit_required: Decimal
    paid_amount: Decimal
    due_date: date | None
    notes: str
    outputs_generated_at: object | None
    items: list[ItemOut] = []
    stage_log: list[StageLogOut] = []
    # planned durations (company settings): how far the order is and when it should be delivered
    progress_pct: int | None = None
    stage_due_at: datetime | None = None
    expected_delivery: date | None = None
    late: bool = False


def _with_progress(db, ctx, outs: list[WorkOrderOut], orders: list[WorkOrder]) -> None:
    from app.modules.org.settings import get_company_settings
    from app.modules.production.progress import progress, stage_entered

    durations = get_company_settings(db, ctx.company_id).stage_durations_days
    entered = stage_entered(db, [o.id for o in orders])
    for out, wo in zip(outs, orders):
        for k, v in progress(wo, entered.get(wo.id, {}), durations).items():
            setattr(out, k, v)


def _wo_out(db, wo: WorkOrder, full: bool = True, ctx=None) -> WorkOrderOut:
    out = WorkOrderOut.model_validate(wo)
    out.stage_name = STAGE_NAMES.get(wo.stage, wo.stage)
    if ctx is not None:
        _with_progress(db, ctx, [out], [wo])
    if full:
        out.items = [ItemOut.model_validate(i) for i in db.scalars(
            select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id).order_by(WorkOrderItem.position))]
        out.stage_log = [StageLogOut.model_validate(l) for l in db.scalars(
            select(WorkOrderStageLog).where(WorkOrderStageLog.work_order_id == wo.id).order_by(WorkOrderStageLog.at))]
    return out


def _log_stage(db, ctx, wo, from_stage, to_stage, note=""):
    db.add(WorkOrderStageLog(work_order_id=wo.id, from_stage=from_stage, to_stage=to_stage, user_id=ctx.user_id,
                             note=note))


def _get_wo(db, ctx, wo_id, permission="workorders.read") -> WorkOrder:
    wo = get_or_404(db, WorkOrder, wo_id)
    ctx.require(permission, wo.branch_id)
    return wo


@router.get("/work-orders", response_model=Page[WorkOrderOut])
def list_work_orders(stage: str | None = None, customer_id: uuid.UUID | None = None, params: PageParams = Depends(),
                     dc=Depends(require("workorders.read"))):
    db, ctx = dc
    stmt = select(WorkOrder).where(WorkOrder.deleted_at.is_(None)).order_by(WorkOrder.created_at.desc())
    stmt = branch_scope(stmt, ctx, "workorders.read", WorkOrder.branch_id)
    if stage:
        stmt = stmt.where(WorkOrder.stage == stage)
    if customer_id:
        stmt = stmt.where(WorkOrder.customer_id == customer_id)
    page = paginate(db, stmt, params, WorkOrderOut)
    for o in page["items"]:
        o.stage_name = STAGE_NAMES.get(o.stage, o.stage)
    orders = {w.id: w for w in db.scalars(select(WorkOrder).where(WorkOrder.id.in_([o.id for o in page["items"]])))}
    _with_progress(db, ctx, page["items"], [orders[o.id] for o in page["items"]])
    return page


@router.post("/work-orders", response_model=WorkOrderOut, status_code=201)
def create_work_order(body: WorkOrderIn, dc=Depends(require("workorders.create"))):
    """Open an order at the survey stage (before any quotation)."""
    db, ctx = dc
    ctx.require("workorders.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    get_or_404(db, Customer, body.customer_id)
    from app.modules.hr.router import salesperson_for

    data = body.model_dump()
    data["salesperson_id"] = salesperson_for(db, ctx, body.salesperson_id)
    wo = WorkOrder(number=next_number(db, "wo", "WO", branch.code), stage="survey", **data)
    db.add(wo)
    db.flush()
    _log_stage(db, ctx, wo, None, "survey")
    audit(db, wo, "create")
    db.commit()
    return _wo_out(db, wo, ctx=ctx)


@router.post("/work-orders/from-quotation", response_model=WorkOrderOut, status_code=201)
def from_quotation(body: FromQuotationIn, dc=Depends(require("workorders.create"))):
    db, ctx = dc
    q = get_or_404(db, Quotation, body.quotation_id)
    ctx.require("workorders.create", q.branch_id)
    if q.status != "accepted":
        raise Conflict("Quotation must be accepted first", code="QUOTE_NOT_ACCEPTED")
    if db.scalar(select(WorkOrder).where(WorkOrder.quotation_id == q.id, WorkOrder.deleted_at.is_(None))):
        raise Conflict("Quotation already has a work order", code="QUOTE_ALREADY_ORDERED")
    settings = get_company_settings(db, ctx.company_id)
    if body.work_order_id:
        wo = _get_wo(db, ctx, body.work_order_id, "workorders.write")
        if wo.customer_id != q.customer_id or wo.stage not in ("survey", "quotation"):
            raise Conflict("Work order cannot take this quotation", code="WO_MISMATCH")
        before_stage = wo.stage
    else:
        branch = db.get(Branch, q.branch_id)
        wo = WorkOrder(number=next_number(db, "wo", "WO", branch.code), customer_id=q.customer_id,
                       branch_id=q.branch_id, stage="quotation")
        db.add(wo)
        db.flush()
        before_stage = None
    wo.quotation_id = q.id
    wo.salesperson_id = q.salesperson_id or wo.salesperson_id
    wo.total = q.total
    wo.due_date = body.due_date or wo.due_date
    wo.deposit_required = body.deposit_required if body.deposit_required is not None else \
        money(q.total * settings.deposit_pct / 100)
    # every line is a unit to make, an arch (أرج) line included (its price is inside its unit)
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)
                           .order_by(QuotationLine.position, QuotationLine.parent_line_id.is_not(None))):
        db.add(WorkOrderItem(work_order_id=wo.id, position=line.position, location=line.location,
                             model_id=line.model_id, formula_set_version_id=line.formula_set_version_id,
                             opening_width_mm=line.opening_width_mm, opening_height_mm=line.opening_height_mm,
                             params=line.params, color_code=line.color_code,
                             glass_material_code=line.glass_material_code, qty=line.qty,
                             unit_price=line.unit_price, calc=line.calc))
    wo.stage = "quotation"
    _log_stage(db, ctx, wo, before_stage, "quotation", f"quotation {q.number}")
    audit(db, wo, "create" if before_stage is None else "update")
    db.commit()
    return _wo_out(db, wo, ctx=ctx)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderOut)
def get_work_order(wo_id: uuid.UUID, dc=Depends(require("workorders.read"))):
    db, ctx = dc
    return _wo_out(db, _get_wo(db, ctx, wo_id), ctx=ctx)


@router.patch("/work-orders/{wo_id}", response_model=WorkOrderOut)
def update_work_order(wo_id: uuid.UUID, body: WorkOrderUpdate, dc=Depends(require("workorders.write"))):
    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id, "workorders.write")
    check_version(wo, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("salesperson_id"):
        from app.modules.hr.router import salesperson_for
        salesperson_for(db, ctx, data["salesperson_id"])
    before = snapshot(wo)
    apply_changes(wo, data)
    audit(db, wo, "update", before)
    db.commit()
    return _wo_out(db, wo, ctx=ctx)


class StageIn(BaseModel):
    version: int
    to: str
    note: str = ""


@router.post("/work-orders/{wo_id}/stage", response_model=WorkOrderOut)
def change_stage(wo_id: uuid.UUID, body: StageIn, dc=Depends(require("workorders.stage"))):
    """Move forward one stage, or cancel (before delivery)."""
    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id, "workorders.stage")
    check_version(wo, body.version)
    current = wo.stage
    if body.to == "cancelled":
        if current in ("delivered", "cancelled"):
            raise Conflict("Cannot cancel", code="INVALID_TRANSITION")
    else:
        if current == "cancelled" or body.to not in STAGES or STAGES.index(body.to) != STAGES.index(current) + 1:
            raise Conflict(f"Cannot go from {current} to {body.to}", code="INVALID_TRANSITION",
                           details={"allowed": STAGES[STAGES.index(current) + 1] if current in STAGES[:-1] else None})
        if body.to == "approved":
            if wo.quotation_id is None:
                raise Conflict("No accepted quotation", code="NO_QUOTATION")
            if wo.paid_amount < wo.deposit_required:
                raise Conflict("Deposit not paid", code="DEPOSIT_REQUIRED",
                               details={"required": str(wo.deposit_required), "paid": str(wo.paid_amount)})
        if body.to == "manufacturing":
            wo.outputs = generate_outputs(db, wo)
            wo.outputs_generated_at = utcnow()
            errors = [i for i in wo.outputs["issues"] if i.get("level") == "error"]
            if errors:
                raise ValidationFailed("Manufacturing outputs have errors", code="MANUFACTURING_ERRORS",
                                       details=errors)
    before = snapshot(wo)
    wo.stage = body.to
    _log_stage(db, ctx, wo, current, body.to, body.note)
    audit(db, wo, "update", before)
    db.commit()
    return _wo_out(db, wo, ctx=ctx)


@router.post("/work-orders/{wo_id}/manufacturing/generate")
def generate(wo_id: uuid.UUID, dc=Depends(require("workorders.write"))):
    """(Re)build cut lists etc. Allowed until production starts; then outputs are frozen."""
    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id, "workorders.write")
    if wo.stage in FROZEN_STAGES:
        raise Conflict("Outputs are frozen once manufacturing started", code="OUTPUTS_FROZEN")
    wo.outputs = generate_outputs(db, wo)
    wo.outputs_generated_at = utcnow()
    db.commit()
    return wo.outputs


@router.get("/work-orders/{wo_id}/manufacturing")
def get_outputs(wo_id: uuid.UUID, dc=Depends(require("workorders.read"))):
    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id)
    if not wo.outputs:
        if wo.stage in FROZEN_STAGES:
            raise Conflict("No outputs", code="NO_OUTPUTS")
        return generate_outputs(db, wo)
    return wo.outputs


class NeedOut(BaseModel):
    kind: str                     # profile | glass | accessory
    sku: str
    material_code: str
    name: str
    unit: str
    qty: Decimal                  # in the stock unit: metres of whole bars, m² of glass, pieces
    bars: int | None = None       # profiles: whole bars after cutting optimisation
    bar_length_mm: Decimal | None = None
    pieces: int | None = None     # glass panes
    unit_cost: Decimal | None = None


@router.get("/work-orders/{wo_id}/material-needs", response_model=list[NeedOut])
def material_needs(wo_id: uuid.UUID, dc=Depends(require("workorders.read"))):
    """What the order needs, from its deductions (cut list after optimisation), glass and each model's
    accessories: the lines of a goods order for this customer."""
    from app.modules.library.service import find_material

    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id)
    out = wo.outputs or generate_outputs(db, wo)   # not saved: only reading the needs
    cost = {c["sku"]: Decimal(str(c["unit_cost"])) for c in out.get("costs", [])}
    needs: list[NeedOut] = []
    planned = {p["sku"]: p for p in out.get("optimisation", [])}
    for g in out.get("cut_list", []):
        plan = planned.get(g["sku"])
        if plan:
            qty = Decimal(str(plan["bar_length_mm"])) * plan["bars_count"] / 1000
            needs.append(NeedOut(kind="profile", sku=g["sku"], material_code=g["material_code"],
                                 name=g.get("material_name") or g["material_code"], unit="m", qty=qty,
                                 bars=plan["bars_count"], bar_length_mm=Decimal(str(plan["bar_length_mm"]))))
        else:
            needs.append(NeedOut(kind="profile", sku=g["sku"], material_code=g["material_code"],
                                 name=g.get("material_name") or g["material_code"], unit="m",
                                 qty=Decimal(str(g["total_length_mm"])) / 1000))
    panes: dict[str, int] = {}
    for gl in out.get("glass", []):
        panes[gl["material_code"] or "-"] = panes.get(gl["material_code"] or "-", 0) + int(gl["qty"])
    for code, area in out.get("glass_area_by_type", {}).items():
        if code == "-":
            continue
        m = find_material(db, code)
        needs.append(NeedOut(kind="glass", sku=code, material_code=code, name=m.name if m else code, unit="m2",
                             qty=Decimal(str(area)), pieces=panes.get(code)))
    for a in out.get("accessories", []):
        needs.append(NeedOut(kind="accessory", sku=a["sku"], material_code=a["material_code"],
                             name=a.get("material_name") or a["material_code"], unit=a.get("unit") or "pcs",
                             qty=Decimal(str(a["qty"]))))
    for n in needs:
        n.unit_cost = cost.get(n.sku)
        n.qty = n.qty.quantize(Decimal("0.001"))
    return needs


@router.delete("/work-orders/{wo_id}", response_model=DeleteResult)
def delete_work_order(wo_id: uuid.UUID, dc=Depends(require("workorders.delete"))):
    """Only before anything happened to it: once money is received or it is invoiced, it is cancelled
    (stage "cancelled") instead, so the records stay consistent."""
    from app.modules.invoicing.models import Invoice

    db, ctx = dc
    wo = _get_wo(db, ctx, wo_id, "workorders.delete")
    if wo.paid_amount > 0 or db.scalar(
            select(Invoice.id).where(Invoice.work_order_id == wo.id, Invoice.deleted_at.is_(None),
                                     Invoice.status != "cancelled")):
        raise Conflict("Work order has payments or an invoice", code="WO_IN_USE")
    before = snapshot(wo)
    wo.deleted_at = utcnow()
    audit(db, wo, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")
