from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.modules.deletions.router import deletable
from app.api.common import DeleteResult, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.models import Customer, SiteSurvey, SurveyOpening
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.hr.router import salesperson_for
from app.modules.library.models import ProductModel
from app.modules.library.service import calculate_model, model_image
from app.modules.org.models import Branch
from app.modules.org.settings import get_company_settings
from app.modules.sales.models import Quotation, QuotationLine
from app.modules.sales.pricing import CostResolver, cost_of_calc, guide_prices, money
from app.tenancy.context import require

router = APIRouter(tags=["sales"])


# ---------------------------------------------------------------- quotations
class LineIn(BaseModel):
    location: str = ""
    model_id: uuid.UUID
    opening_width_mm: Decimal = Field(gt=0)
    opening_height_mm: Decimal = Field(gt=0)
    total_height_mm: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    top_model_id: uuid.UUID | None = None      # arch model (default: company setting)
    params: dict = {}
    color_code: str | None = None
    glass_material_code: str | None = None
    qty: int = Field(1, ge=1)
    manual_unit_price: Decimal | None = Field(None, ge=0)
    price_per_m2: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    notes: str = ""


class LineUpdate(VersionedUpdate):
    location: str | None = None
    opening_width_mm: Decimal | None = Field(None, gt=0)
    opening_height_mm: Decimal | None = Field(None, gt=0)
    total_height_mm: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    top_model_id: uuid.UUID | None = None
    params: dict | None = None
    color_code: str | None = None
    glass_material_code: str | None = None
    qty: int | None = Field(None, ge=1)
    manual_unit_price: Decimal | None = Field(None, ge=0)
    price_per_m2: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    notes: str | None = None


class LineOut(Record):
    position: int
    location: str
    model_id: uuid.UUID
    formula_set_version_id: uuid.UUID
    opening_width_mm: Decimal
    opening_height_mm: Decimal
    total_height_mm: Decimal | None
    top_model_id: uuid.UUID | None
    parent_line_id: uuid.UUID | None
    params: dict
    color_code: str | None
    glass_material_code: str | None
    qty: int
    area_m2: Decimal
    unit_cost: Decimal
    unit_price: Decimal
    manual_unit_price: Decimal | None
    price_per_m2: Decimal | None
    billed_area_m2: Decimal
    line_total: Decimal
    cost_breakdown: dict
    calc: dict
    notes: str
    model_name: str = ""
    model_code: str = ""
    model_image_id: uuid.UUID | None = None
    # دليل المبيعات for one unit: the fair price (cost + fair margin) and the top price (cost + top margin)
    fair_unit_price: Decimal | None = None
    top_unit_price: Decimal | None = None
    fair_price_per_m2: Decimal | None = None
    top_price_per_m2: Decimal | None = None
    priced: bool = True                              # False: the salesperson has not typed a price yet
    model_deleted: bool = False                      # its model was deleted from the library: replace it


class QuotationIn(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_id: uuid.UUID | None = None
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    discount_amount: Decimal = Field(Decimal(0), ge=0)
    valid_until: date | None = None
    notes: str = ""
    terms: str | None = None
    salesperson_id: uuid.UUID | None = None
    lines: list[LineIn] = []


class QuotationUpdate(VersionedUpdate):
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    discount_amount: Decimal | None = Field(None, ge=0)
    valid_until: date | None = None
    notes: str | None = None
    terms: str | None = None
    salesperson_id: uuid.UUID | None = None


class QuotationOut(Record):
    number: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_id: uuid.UUID | None
    price_list_id: uuid.UUID | None = None
    status: str
    issue_date: date | None
    valid_until: date | None
    discount_amount: Decimal
    tax_pct: Decimal
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    total_cost: Decimal
    notes: str
    terms: str
    salesperson_id: uuid.UUID | None = None
    fair_total: Decimal
    top_total: Decimal
    net_total: Decimal = Decimal(0)                  # before tax: subtotal − discount
    price_approved_total: Decimal | None = None
    price_approved_at: datetime | None = None
    price_approval_note: str = ""
    needs_price_approval: bool = False               # under the fair price and not approved by the sales manager
    unpriced_lines: int = 0
    lines: list[LineOut] = []


EDITABLE = ("draft", "sent")
LINE_ORDER = (QuotationLine.position, QuotationLine.parent_line_id.is_not(None))   # a unit, then its arch
UNITS = QuotationLine.parent_line_id.is_(None)
TRANSITIONS = {"draft": {"sent", "accepted", "rejected"}, "sent": {"accepted", "rejected", "expired", "draft"},
               "rejected": {"draft"}, "expired": {"draft"}, "accepted": set()}


def _quote_out(db, q: Quotation, with_calc: bool = True) -> QuotationOut:
    out = QuotationOut.model_validate(q)
    lines = []
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id).order_by(*LINE_ORDER)):
        lo = LineOut.model_validate(line)
        model = db.get(ProductModel, line.model_id)
        lo.model_name, lo.model_code = (model.name, model.code) if model else ("", "")
        lo.model_image_id = model_image(model, line.color_code)
        lo.model_deleted = model is not None and model.deleted_at is not None
        guide = line.cost_breakdown or {}
        if guide.get("fair_unit_price") is not None:
            lo.fair_unit_price, lo.top_unit_price = Decimal(guide["fair_unit_price"]), Decimal(guide["top_unit_price"])
            if line.billed_area_m2:
                lo.fair_price_per_m2 = money(lo.fair_unit_price / line.billed_area_m2)
                lo.top_price_per_m2 = money(lo.top_unit_price / line.billed_area_m2)
        lo.priced = line.parent_line_id is not None or _is_priced(line)
        if not with_calc:
            lo.calc = {}
        lines.append(lo)
    out.lines = lines
    out.net_total = _net(q)
    out.unpriced_lines = sum(1 for l in lines if not l.priced)
    out.needs_price_approval = _needs_price_approval(q)
    return out


def _is_priced(line: QuotationLine) -> bool:
    return line.price_per_m2 is not None or line.manual_unit_price is not None or \
        "fair_unit_price" not in (line.cost_breakdown or {})         # priced before the guide (price lists)


def _net(q: Quotation) -> Decimal:
    return max(q.subtotal - q.discount_amount, Decimal(0))


def _needs_price_approval(q: Quotation) -> bool:
    """The total after the discount is under the fair total and the sales manager has not approved that much."""
    net = _net(q)
    return net < q.fair_total and (q.price_approved_total is None or net < q.price_approved_total)


class Pricer:
    """Cost of one opening from the published model and the company's costs, and the guide prices on it."""

    def __init__(self, db, ctx):
        self.db, self.ctx = db, ctx
        self.settings = get_company_settings(db, ctx.company_id)
        self.resolver = CostResolver(db)
        default_arch = self.settings.default_arch_model_id
        self.default_arch = uuid.UUID(default_arch) if default_arch else None

    def billed_area(self, area: Decimal) -> Decimal:
        return max(area, self.settings.min_billed_area_m2)

    def _calc(self, model_id, width_mm, height_mm, params, location, part):
        calc = calculate_model(self.db, self.ctx, model_id, opening_width_mm=width_mm, opening_height_mm=height_mm,
                               params=params)
        errors = [i for i in calc["issues"] if i["level"] == "error"]
        if errors:
            raise ValidationFailed("Opening cannot be manufactured with this model", code="CALC_INVALID",
                                   details={"location": location, "part": part, "issues": errors})
        return calc

    def price(self, model_id, width_mm: Decimal, height_mm: Decimal, params: dict, color: str | None,
              glass: str | None, location: str = "", total_height_mm: Decimal | None = None,
              top_model_id=None) -> dict:
        """A total height above the opening height is a half-circle arch (أرج) on top: a separate fixed unit
        with its own frame, calculated with the arch model at width × (total − height). Its cost is part of
        this unit, and the area for the price is width × total height."""
        calc = self._calc(model_id, width_mm, height_mm, params, location, "unit")
        breakdown = cost_of_calc(self.resolver, calc, color, glass, self.settings.quote_waste_pct)
        unit_cost = breakdown["total"]
        arch = None
        price_height = height_mm
        if total_height_mm is not None and total_height_mm > height_mm:
            price_height = total_height_mm
            arch_model = top_model_id or self.default_arch
            if arch_model is None:
                raise ValidationFailed("Choose the arch model", code="ARCH_MODEL_REQUIRED", details={"location": location})
            arch_h = total_height_mm - height_mm
            arch_calc = self._calc(arch_model, width_mm, arch_h, {}, location, "arch")
            arch_cost = cost_of_calc(self.resolver, arch_calc, color, glass, self.settings.quote_waste_pct)
            unit_cost += arch_cost["total"]
            arch = {"model_id": arch_model, "height_mm": arch_h, "calc": arch_calc, "breakdown": arch_cost}
        area = (width_mm * price_height / Decimal(1_000_000)).quantize(Decimal("0.0001"))
        unit_cost = money(unit_cost + self.settings.labor_cost_per_m2 * area)
        fair, top = guide_prices(unit_cost, self.settings.fair_margin_pct, self.settings.top_margin_pct)
        return {"calc": calc, "breakdown": breakdown, "arch": arch, "unit_cost": unit_cost, "area": area,
                "billed_area": self.billed_area(area), "fair": fair, "top": top}


def _price_line(db, ctx, q: Quotation, line: QuotationLine, pricer: Pricer) -> None:
    if line.parent_line_id is not None:
        raise Conflict("The arch line follows its unit", code="ARCH_LINE_MANAGED")
    if line.price_per_m2 is None and line.manual_unit_price is None and line.unit_price and \
            "fair_unit_price" not in (line.cost_breakdown or {}):
        line.manual_unit_price = line.unit_price        # a price from an old price list stays the line's price
    r = pricer.price(line.model_id, line.opening_width_mm, line.opening_height_mm, line.params, line.color_code,
                     line.glass_material_code, line.location, line.total_height_mm, line.top_model_id)
    calc, breakdown, arch = r["calc"], r["breakdown"], r["arch"]
    line.formula_set_version_id = uuid.UUID(calc["meta"]["formula_set_version_id"])
    line.calc = calc
    line.area_m2 = r["area"]
    line.billed_area_m2 = r["billed_area"]
    line.unit_cost = r["unit_cost"]
    cost_lines = breakdown["lines"] + ([{**l, "part": "arch"} for l in arch["breakdown"]["lines"]] if arch else [])
    missing = sorted(set(breakdown["missing_costs"]) | set(arch["breakdown"]["missing_costs"] if arch else []))
    line.cost_breakdown = {"total": str(r["unit_cost"]), "lines": cost_lines, "missing_costs": missing,
                           "labor": str(money(pricer.settings.labor_cost_per_m2 * r["area"])),
                           "fair_unit_price": str(r["fair"]), "top_unit_price": str(r["top"])}
    # the salesperson's price: per m², or for the unit; none typed yet = 0 (the quotation cannot be sent)
    if line.price_per_m2 is not None:
        line.unit_price = money(r["billed_area"] * line.price_per_m2)
    elif line.manual_unit_price is not None:
        line.unit_price = line.manual_unit_price
    else:
        line.unit_price = Decimal(0)
    line.line_total = money(line.unit_price * line.qty)
    _sync_arch_line(db, q, line, arch)


def _sync_arch_line(db, q: Quotation, line: QuotationLine, arch: dict | None) -> None:
    """Keep the unit's arch line (own frame, made with the arch model) in step with the unit."""
    if line not in db:
        db.add(line)
    db.flush()
    child = db.scalar(select(QuotationLine).where(QuotationLine.parent_line_id == line.id))
    if arch is None:
        if child is not None:
            db.delete(child)
            db.flush()
        return
    if child is None:
        child = QuotationLine(quotation_id=q.id, parent_line_id=line.id)
        db.add(child)
    child.position = line.position
    child.location = ("أرج " + line.location).strip()
    child.model_id = arch["model_id"]
    child.formula_set_version_id = uuid.UUID(arch["calc"]["meta"]["formula_set_version_id"])
    child.opening_width_mm = line.opening_width_mm
    child.opening_height_mm = arch["height_mm"]
    child.params, child.color_code, child.glass_material_code = {}, line.color_code, line.glass_material_code
    child.qty = line.qty
    child.area_m2 = (line.opening_width_mm * arch["height_mm"] / Decimal(1_000_000)).quantize(Decimal("0.0001"))
    child.billed_area_m2 = Decimal(0)
    child.calc = arch["calc"]
    child.cost_breakdown = {**arch["breakdown"], "total": str(arch["breakdown"]["total"]), "in_parent": True}
    child.unit_cost = child.unit_price = child.line_total = Decimal(0)   # costed and priced in the unit
    child.notes = ""
    db.flush()


def _totals(db, q: Quotation) -> None:
    lines = list(db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)))
    q.subtotal = money(sum((l.line_total for l in lines), Decimal(0)))
    q.total_cost = money(sum((l.unit_cost * l.qty for l in lines), Decimal(0)))
    guide = [((l.cost_breakdown or {}).get("fair_unit_price"), (l.cost_breakdown or {}).get("top_unit_price"), l.qty)
             for l in lines if l.parent_line_id is None]
    q.fair_total = money(sum((Decimal(f) * n for f, _, n in guide if f is not None), Decimal(0)))
    q.top_total = money(sum((Decimal(t) * n for _, t, n in guide if t is not None), Decimal(0)))
    taxable = max(q.subtotal - q.discount_amount, Decimal(0))
    q.tax_amount = money(taxable * q.tax_pct / 100)
    q.total = money(taxable + q.tax_amount)
    q.updated_at = utcnow()


def _get_quote(db, ctx, quote_id, permission="quotes.read") -> Quotation:
    q = get_or_404(db, Quotation, quote_id)
    ctx.require(permission, q.branch_id)
    return q


@router.get("/quotations", response_model=Page[QuotationOut])
def list_quotations(customer_id: uuid.UUID | None = None, status: str | None = None,
                    params: PageParams = Depends(), dc=Depends(require("quotes.read"))):
    db, ctx = dc
    stmt = select(Quotation).where(Quotation.deleted_at.is_(None)).order_by(Quotation.created_at.desc())
    stmt = branch_scope(stmt, ctx, "quotes.read", Quotation.branch_id)
    if customer_id:
        stmt = stmt.where(Quotation.customer_id == customer_id)
    if status:
        stmt = stmt.where(Quotation.status == status)
    return paginate(db, stmt, params, QuotationOut)


@router.post("/quotations", response_model=QuotationOut, status_code=201)
def create_quotation(body: QuotationIn, dc=Depends(require("quotes.create"))):
    db, ctx = dc
    ctx.require("quotes.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    customer = get_or_404(db, Customer, body.customer_id)
    settings = get_company_settings(db, ctx.company_id)
    lines = list(body.lines)
    if body.survey_id:
        survey = get_or_404(db, SiteSurvey, body.survey_id)
        if survey.customer_id != customer.id:
            raise ValidationFailed("Survey belongs to another customer", code="SURVEY_CUSTOMER")
        if not lines:
            for o in db.scalars(select(SurveyOpening).where(SurveyOpening.survey_id == survey.id)
                                .order_by(SurveyOpening.position)):
                if o.model_id is None:
                    raise ValidationFailed(f"Opening '{o.location}' has no model", code="OPENING_WITHOUT_MODEL")
                lines.append(LineIn(location=o.location, model_id=o.model_id, opening_width_mm=o.opening_width_mm,
                                    total_height_mm=o.total_height_mm, top_model_id=o.top_model_id,
                                    opening_height_mm=o.opening_height_mm, params=o.params, color_code=o.color_code,
                                    glass_material_code=o.glass_material_code, qty=o.qty, notes=o.notes))
    q = Quotation(number=next_number(db, "quote", "QT", branch.code), customer_id=customer.id, branch_id=branch.id,
                  survey_id=body.survey_id, issue_date=date.today(),
                  valid_until=body.valid_until or date.today() + timedelta(days=settings.quote_validity_days),
                  tax_pct=body.tax_pct if body.tax_pct is not None else settings.default_tax_pct,
                  discount_amount=body.discount_amount, notes=body.notes,
                  terms=body.terms if body.terms is not None else settings.quote_terms,
                  salesperson_id=salesperson_for(db, ctx, body.salesperson_id))
    db.add(q)
    db.flush()
    pricer = Pricer(db, ctx)
    for i, l in enumerate(lines, 1):
        line = QuotationLine(quotation_id=q.id, position=i, **l.model_dump())
        _price_line(db, ctx, q, line, pricer)       # adds the line (and its arch line)
    _totals(db, q)
    audit(db, q, "create")
    db.commit()
    return _quote_out(db, q)


@router.get("/quotations/{quote_id}", response_model=QuotationOut)
def get_quotation(quote_id: uuid.UUID, with_calc: bool = True, dc=Depends(require("quotes.read"))):
    db, ctx = dc
    return _quote_out(db, _get_quote(db, ctx, quote_id), with_calc)


@router.patch("/quotations/{quote_id}", response_model=QuotationOut)
def update_quotation(quote_id: uuid.UUID, body: QuotationUpdate, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    check_version(q, body.version)
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    before = snapshot(q)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("salesperson_id"):
        salesperson_for(db, ctx, data["salesperson_id"])
    apply_changes(q, data)
    _totals(db, q)
    audit(db, q, "update", before)
    db.commit()
    return _quote_out(db, q)


@router.post("/quotations/{quote_id}/lines", response_model=QuotationOut, status_code=201)
def add_line(quote_id: uuid.UUID, body: LineIn, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    last = db.scalar(select(func.max(QuotationLine.position)).where(QuotationLine.quotation_id == q.id)) or 0
    line = QuotationLine(quotation_id=q.id, position=last + 1, **body.model_dump())
    _price_line(db, ctx, q, line, Pricer(db, ctx))
    _totals(db, q)
    db.commit()
    return _quote_out(db, q)


@router.patch("/quotation-lines/{line_id}", response_model=QuotationOut)
def update_line(line_id: uuid.UUID, body: LineUpdate, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    line = get_or_404(db, QuotationLine, line_id)
    q = _get_quote(db, ctx, line.quotation_id, "quotes.write")
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    check_version(line, body.version)
    before = snapshot(line)
    apply_changes(line, body.model_dump(exclude_unset=True, exclude={"version"}))
    _price_line(db, ctx, q, line, Pricer(db, ctx))
    _totals(db, q)
    audit(db, line, "update", before)
    db.commit()
    return _quote_out(db, q)


@router.delete("/quotation-lines/{line_id}", response_model=QuotationOut)
def delete_line(line_id: uuid.UUID, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    line = get_or_404(db, QuotationLine, line_id)
    q = _get_quote(db, ctx, line.quotation_id, "quotes.write")
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    if line.parent_line_id is not None:
        raise Conflict("The arch line follows its unit", code="ARCH_LINE_MANAGED")
    before = snapshot(line)
    for child in db.scalars(select(QuotationLine).where(QuotationLine.parent_line_id == line.id)):
        db.delete(child)
    db.delete(line)
    db.flush()
    audit(db, line, "delete", before)
    _totals(db, q)
    db.commit()
    return _quote_out(db, q)


class StatusIn(BaseModel):
    version: int
    status: str


@router.post("/quotations/{quote_id}/status", response_model=QuotationOut)
def set_status(quote_id: uuid.UUID, body: StatusIn, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    check_version(q, body.version)
    if body.status not in TRANSITIONS.get(q.status, set()):
        raise Conflict(f"Cannot go from {q.status} to {body.status}", code="INVALID_TRANSITION")
    if body.status in ("sent", "accepted"):
        if any(not _is_priced(l) for l in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id,
                                                                                  UNITS))):
            raise Conflict("Some lines have no price yet", code="QUOTE_UNPRICED")
        if _needs_price_approval(q):
            raise Conflict("The price is under the fair price: the sales manager must approve it",
                           code="PRICE_APPROVAL_REQUIRED",
                           details={"net_total": str(_net(q)), "fair_total": str(q.fair_total)})
    before = snapshot(q)
    q.status = body.status
    audit(db, q, "update", before)
    from app.modules.notifications.router import alert, customer_name
    word = {"sent": "اتبعت للعميل", "accepted": "العميل وافق عليه", "rejected": "العميل رفضه", "draft": "رجع مسودة"}
    alert(db, ctx, "sales", q.branch_id, f"عرض السعر {q.number} {word.get(q.status, q.status)}",
          customer_name(db, q.customer_id), f"quotations/{q.id}")
    db.commit()
    return _quote_out(db, q, with_calc=False)


class PriceApprovalIn(BaseModel):
    version: int
    note: str = ""


@router.post("/quotations/{quote_id}/request-price-approval", response_model=QuotationOut)
def request_price_approval(quote_id: uuid.UUID, dc=Depends(require("quotes.write"))):
    """The salesperson asks the sales manager to approve a price under the fair price (a notification)."""
    from app.modules.notifications.router import alert, customer_name, recipients

    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    if not _needs_price_approval(q):
        raise Conflict("The price does not need approval", code="PRICE_APPROVAL_NOT_NEEDED")
    alert(db, ctx, "sales", q.branch_id, f"عرض السعر {q.number} محتاج موافقتك على السعر",
          f"{customer_name(db, q.customer_id)} · {_net(q)} والسعر العادل {q.fair_total}", f"quotations/{q.id}",
          users=recipients(db, "quotes.approve_price", q.branch_id))
    db.commit()
    return _quote_out(db, q, with_calc=False)


@router.post("/quotations/{quote_id}/approve-price", response_model=QuotationOut)
def approve_price(quote_id: uuid.UUID, body: PriceApprovalIn, dc=Depends(require("quotes.approve_price"))):
    """The sales manager approves the quotation's current total under the fair price. Lowering it again needs
    another approval; raising it does not."""
    from app.modules.notifications.router import alert, customer_name

    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.approve_price")
    check_version(q, body.version)
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    if not _needs_price_approval(q):
        raise Conflict("The price does not need approval", code="PRICE_APPROVAL_NOT_NEEDED")
    before = snapshot(q)
    q.price_approved_total, q.price_approved_at, q.price_approved_by = _net(q), utcnow(), ctx.user_id
    q.price_approval_note = body.note
    q.updated_at = utcnow()
    audit(db, q, "update", before)
    alert(db, ctx, "sales", q.branch_id, f"مدير المبيعات وافق على سعر عرض {q.number}",
          customer_name(db, q.customer_id), f"quotations/{q.id}", users={q.created_by} if q.created_by else set())
    db.commit()
    return _quote_out(db, q, with_calc=False)


@router.post("/quotations/{quote_id}/recalculate", response_model=QuotationOut)
def recalculate(quote_id: uuid.UUID, dc=Depends(require("quotes.write"))):
    """Re-run every line with the CURRENT published formulas and prices (explicit action)."""
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    pricer = Pricer(db, ctx)
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id, UNITS)):
        _price_line(db, ctx, q, line, pricer)
    _totals(db, q)
    db.commit()
    return _quote_out(db, q)


class PricePerM2In(BaseModel):
    version: int
    price_per_m2: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)


@router.post("/quotations/{quote_id}/price-per-m2", response_model=QuotationOut)
def set_price_per_m2(quote_id: uuid.UUID, body: PricePerM2In, dc=Depends(require("quotes.write"))):
    """One price per m² for every line (empty = back to each line's own price)."""
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    check_version(q, body.version)
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    before = snapshot(q)
    pricer = Pricer(db, ctx)
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id, UNITS)):
        line.price_per_m2 = body.price_per_m2
        _price_line(db, ctx, q, line, pricer)
    _totals(db, q)
    audit(db, q, "update", before)
    db.commit()
    return _quote_out(db, q)


# ---------------------------------------------------------------- guide prices of a survey
class OpeningPrice(BaseModel):
    position: int
    location: str
    qty: int
    area_m2: Decimal | None = None
    billed_area_m2: Decimal | None = None
    unit_cost: Decimal | None = None
    fair_unit_price: Decimal | None = None
    top_unit_price: Decimal | None = None
    missing_costs: list[str] = []
    error: str | None = None


class SurveyPricing(BaseModel):
    survey_id: uuid.UUID
    fair_margin_pct: Decimal
    top_margin_pct: Decimal
    cost_total: Decimal
    fair_total: Decimal                   # the lowest without the sales manager
    top_total: Decimal
    fair_price_per_m2: Decimal | None     # total / billed area
    top_price_per_m2: Decimal | None
    area_m2: Decimal
    billed_area_m2: Decimal
    priced: int
    unpriced: int
    missing_costs: list[str] = []         # materials without a price: the cost is short of them
    openings: list[OpeningPrice]


@router.get("/surveys/{survey_id}/pricing", response_model=SurveyPricing)
def survey_pricing(survey_id: uuid.UUID, dc=Depends(require("quotes.read"))):
    """دليل المبيعات: the company's cost of the survey's openings (with a model) at their sizes, and two prices on
    it: the fair price (cost + fair margin) and the top price (cost + top margin). Each unit bills at least the
    company's minimum area for the price per m²."""
    from app.core.errors import AppError

    db, ctx = dc
    survey = get_or_404(db, SiteSurvey, survey_id)
    ctx.require("surveys.read", survey.branch_id)
    pricer = Pricer(db, ctx)
    rows, missing = [], set()
    cost = fair = top = area_sum = billed_sum = Decimal(0)
    for o in db.scalars(select(SurveyOpening).where(SurveyOpening.survey_id == survey.id)
                        .order_by(SurveyOpening.position)):
        row = OpeningPrice(position=o.position, location=o.location, qty=o.qty)
        if o.model_id is None:
            row.error = "OPENING_WITHOUT_MODEL"
        else:
            try:
                r = pricer.price(o.model_id, o.opening_width_mm, o.opening_height_mm, o.params, o.color_code,
                                 o.glass_material_code, o.location, o.total_height_mm, o.top_model_id)
            except AppError as e:
                row.error = e.code
            else:
                row.area_m2, row.billed_area_m2, row.unit_cost = r["area"], r["billed_area"], r["unit_cost"]
                row.fair_unit_price, row.top_unit_price = r["fair"], r["top"]
                row.missing_costs = sorted(set(r["breakdown"]["missing_costs"]) |
                                           set(r["arch"]["breakdown"]["missing_costs"] if r["arch"] else []))
                missing |= set(row.missing_costs)
                cost += r["unit_cost"] * o.qty
                fair += r["fair"] * o.qty
                top += r["top"] * o.qty
                area_sum += r["area"] * o.qty
                billed_sum += r["billed_area"] * o.qty
        rows.append(row)
    priced = sum(1 for r in rows if r.error is None)
    st = pricer.settings
    return SurveyPricing(survey_id=survey.id, fair_margin_pct=st.fair_margin_pct, top_margin_pct=st.top_margin_pct,
                         cost_total=money(cost), fair_total=money(fair), top_total=money(top),
                         fair_price_per_m2=money(fair / billed_sum) if billed_sum else None,
                         top_price_per_m2=money(top / billed_sum) if billed_sum else None,
                         area_m2=area_sum, billed_area_m2=billed_sum, priced=priced, unpriced=len(rows) - priced,
                         missing_costs=sorted(missing), openings=rows)


# ---------------------------------------------------------------- delete
@deletable(router, "/quotations/{quote_id}", "quotations", ("عرض السعر", Quotation, "number"))
def delete_quotation(quote_id: uuid.UUID, dc=Depends(require("quotes.delete"))):
    """A quotation that became a work order or an invoice stays (cancel those first)."""
    from app.modules.invoicing.models import Invoice
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.delete")
    if db.scalar(select(WorkOrder.id).where(WorkOrder.quotation_id == q.id, WorkOrder.deleted_at.is_(None),
                                            WorkOrder.stage != "cancelled")) or \
            db.scalar(select(Invoice.id).where(Invoice.quotation_id == q.id, Invoice.deleted_at.is_(None),
                                               Invoice.status != "cancelled")):
        raise Conflict("Quotation has a work order or an invoice", code="QUOTE_IN_USE")
    before = snapshot(q)
    q.deleted_at = utcnow()
    audit(db, q, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")
