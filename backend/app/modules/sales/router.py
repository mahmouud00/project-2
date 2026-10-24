from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.numbering import next_number
from app.db.base import utcnow
from app.modules.crm.models import Customer, SiteSurvey, SurveyOpening
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.library.models import ProductModel
from app.modules.library.service import calculate_model
from app.modules.org.models import Branch
from app.modules.org.settings import get_company_settings
from app.modules.sales.models import PriceList, PriceListItem, Quotation, QuotationLine
from app.modules.sales.pricing import CostResolver, cost_of_calc, money, unit_price
from app.tenancy.context import require

router = APIRouter(tags=["sales"])


# ---------------------------------------------------------------- price lists
class PriceListItemIn(BaseModel):
    model_id: uuid.UUID | None = None
    system_id: uuid.UUID | None = None
    margin_pct: Decimal | None = None
    price_per_m2: Decimal | None = Field(None, ge=0)


class PriceListIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str
    customer_type: str | None = Field(None, pattern="^(end|dealer|contractor)$")
    margin_pct: Decimal = Decimal(0)
    labor_cost_per_m2: Decimal = Field(Decimal(0), ge=0)
    min_unit_price: Decimal = Field(Decimal(0), ge=0)
    items: list[PriceListItemIn] = []


class PriceListUpdate(VersionedUpdate):
    name: str | None = None
    customer_type: str | None = Field(None, pattern="^(end|dealer|contractor)$")
    margin_pct: Decimal | None = None
    labor_cost_per_m2: Decimal | None = None
    min_unit_price: Decimal | None = None
    is_active: bool | None = None
    items: list[PriceListItemIn] | None = None


class PriceListItemOut(ORMModel):
    model_id: uuid.UUID | None
    system_id: uuid.UUID | None
    margin_pct: Decimal | None
    price_per_m2: Decimal | None


class PriceListOut(Record):
    code: str
    name: str
    customer_type: str | None
    margin_pct: Decimal
    labor_cost_per_m2: Decimal
    min_unit_price: Decimal
    is_active: bool
    items: list[PriceListItemOut] = []


def _pl_out(db, pl) -> PriceListOut:
    out = PriceListOut.model_validate(pl)
    out.items = [PriceListItemOut.model_validate(i) for i in
                 db.scalars(select(PriceListItem).where(PriceListItem.price_list_id == pl.id))]
    return out


def _set_pl_items(db, pl, items: list[PriceListItemIn]) -> None:
    for old in db.scalars(select(PriceListItem).where(PriceListItem.price_list_id == pl.id)):
        db.delete(old)
    db.flush()
    for i in items:
        if (i.model_id is None) == (i.system_id is None):
            raise ValidationFailed("Each item needs exactly one of model_id / system_id", code="PRICE_ITEM_TARGET")
        db.add(PriceListItem(price_list_id=pl.id, **i.model_dump()))


@router.get("/price-lists", response_model=list[PriceListOut])
def list_price_lists(dc=Depends(require("quotes.read"))):
    db, _ = dc
    return [_pl_out(db, p) for p in db.scalars(select(PriceList).order_by(PriceList.code))]


@router.post("/price-lists", response_model=PriceListOut, status_code=201)
def create_price_list(body: PriceListIn, dc=Depends(require("pricelists.manage"))):
    db, _ = dc
    if db.scalar(select(PriceList).where(PriceList.code == body.code)):
        raise Conflict("Price list code exists", code="DUPLICATE_CODE")
    pl = PriceList(**body.model_dump(exclude={"items"}))
    db.add(pl)
    db.flush()
    _set_pl_items(db, pl, body.items)
    audit(db, pl, "create")
    db.commit()
    return _pl_out(db, pl)


@router.patch("/price-lists/{pl_id}", response_model=PriceListOut)
def update_price_list(pl_id: uuid.UUID, body: PriceListUpdate, dc=Depends(require("pricelists.manage"))):
    db, _ = dc
    pl = get_or_404(db, PriceList, pl_id)
    check_version(pl, body.version)
    before = snapshot(pl)
    apply_changes(pl, body.model_dump(exclude_unset=True, exclude={"version", "items"}))
    if body.items is not None:
        _set_pl_items(db, pl, body.items)
        pl.updated_at = utcnow()
    audit(db, pl, "update", before)
    db.commit()
    return _pl_out(db, pl)


# ---------------------------------------------------------------- quotations
class LineIn(BaseModel):
    location: str = ""
    model_id: uuid.UUID
    opening_width_mm: Decimal = Field(gt=0)
    opening_height_mm: Decimal = Field(gt=0)
    params: dict = {}
    color_code: str | None = None
    glass_material_code: str | None = None
    qty: int = Field(1, ge=1)
    manual_unit_price: Decimal | None = Field(None, ge=0)
    notes: str = ""


class LineUpdate(VersionedUpdate):
    location: str | None = None
    opening_width_mm: Decimal | None = Field(None, gt=0)
    opening_height_mm: Decimal | None = Field(None, gt=0)
    params: dict | None = None
    color_code: str | None = None
    glass_material_code: str | None = None
    qty: int | None = Field(None, ge=1)
    manual_unit_price: Decimal | None = Field(None, ge=0)
    notes: str | None = None


class LineOut(Record):
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
    area_m2: Decimal
    unit_cost: Decimal
    unit_price: Decimal
    manual_unit_price: Decimal | None
    line_total: Decimal
    cost_breakdown: dict
    calc: dict
    notes: str
    model_name: str = ""
    model_image_id: uuid.UUID | None = None


class QuotationIn(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    price_list_id: uuid.UUID | None = None
    survey_id: uuid.UUID | None = None
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    discount_amount: Decimal = Field(Decimal(0), ge=0)
    valid_until: date | None = None
    notes: str = ""
    terms: str | None = None
    lines: list[LineIn] = []


class QuotationUpdate(VersionedUpdate):
    price_list_id: uuid.UUID | None = None
    tax_pct: Decimal | None = Field(None, ge=0, le=100)
    discount_amount: Decimal | None = Field(None, ge=0)
    valid_until: date | None = None
    notes: str | None = None
    terms: str | None = None


class QuotationOut(Record):
    number: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_id: uuid.UUID | None
    price_list_id: uuid.UUID
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
    lines: list[LineOut] = []


EDITABLE = ("draft", "sent")
TRANSITIONS = {"draft": {"sent", "accepted", "rejected"}, "sent": {"accepted", "rejected", "expired", "draft"},
               "rejected": {"draft"}, "expired": {"draft"}, "accepted": set()}


def _quote_out(db, q: Quotation, with_calc: bool = True) -> QuotationOut:
    out = QuotationOut.model_validate(q)
    lines = []
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)
                           .order_by(QuotationLine.position)):
        lo = LineOut.model_validate(line)
        model = db.get(ProductModel, line.model_id)
        lo.model_name, lo.model_image_id = (model.name, model.image_id) if model else ("", None)
        if not with_calc:
            lo.calc = {}
        lines.append(lo)
    out.lines = lines
    return out


def _price_line(db, ctx, q: Quotation, line: QuotationLine, resolver: CostResolver) -> None:
    calc = calculate_model(db, ctx, line.model_id, opening_width_mm=line.opening_width_mm,
                           opening_height_mm=line.opening_height_mm, params=line.params)
    errors = [i for i in calc["issues"] if i["level"] == "error"]
    if errors:
        raise ValidationFailed("Opening cannot be manufactured with this model", code="CALC_INVALID",
                               details={"location": line.location, "issues": errors})
    settings = get_company_settings(db, ctx.company_id)
    breakdown = cost_of_calc(resolver, calc, line.color_code, line.glass_material_code, settings.quote_waste_pct)
    model = db.get(ProductModel, line.model_id)
    pl = db.get(PriceList, q.price_list_id)
    items = list(db.scalars(select(PriceListItem).where(PriceListItem.price_list_id == pl.id)))
    area = (line.opening_width_mm * line.opening_height_mm / Decimal(1_000_000)).quantize(Decimal("0.0001"))
    line.formula_set_version_id = uuid.UUID(calc["meta"]["formula_set_version_id"])
    line.calc = calc
    line.area_m2 = area
    line.unit_cost = breakdown["total"]
    line.cost_breakdown = {**breakdown, "total": str(breakdown["total"])}
    line.unit_price = line.manual_unit_price if line.manual_unit_price is not None else \
        unit_price(pl, items, model.id, model.system_id, area, breakdown["total"])
    line.line_total = money(line.unit_price * line.qty)


def _totals(db, q: Quotation) -> None:
    lines = list(db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)))
    q.subtotal = money(sum((l.line_total for l in lines), Decimal(0)))
    q.total_cost = money(sum((l.unit_cost * l.qty for l in lines), Decimal(0)))
    taxable = max(q.subtotal - q.discount_amount, Decimal(0))
    q.tax_amount = money(taxable * q.tax_pct / 100)
    q.total = money(taxable + q.tax_amount)
    q.updated_at = utcnow()


def _default_price_list(db, customer: Customer) -> PriceList:
    if customer.price_list_id:
        return db.get(PriceList, customer.price_list_id)
    pl = db.scalar(select(PriceList).where(PriceList.customer_type == customer.customer_type, PriceList.is_active)
                   .order_by(PriceList.code))
    if pl is None:
        raise ValidationFailed("No price list for this customer type", code="NO_PRICE_LIST")
    return pl


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
def create_quotation(body: QuotationIn, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    ctx.require("quotes.write", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    customer = get_or_404(db, Customer, body.customer_id)
    settings = get_company_settings(db, ctx.company_id)
    pl = get_or_404(db, PriceList, body.price_list_id) if body.price_list_id else _default_price_list(db, customer)
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
                                    opening_height_mm=o.opening_height_mm, params=o.params, color_code=o.color_code,
                                    glass_material_code=o.glass_material_code, qty=o.qty, notes=o.notes))
    q = Quotation(number=next_number(db, "quote", "QT", branch.code), customer_id=customer.id, branch_id=branch.id,
                  survey_id=body.survey_id, price_list_id=pl.id, issue_date=date.today(),
                  valid_until=body.valid_until or date.today() + timedelta(days=settings.quote_validity_days),
                  tax_pct=body.tax_pct if body.tax_pct is not None else settings.default_tax_pct,
                  discount_amount=body.discount_amount, notes=body.notes,
                  terms=body.terms if body.terms is not None else settings.quote_terms)
    db.add(q)
    db.flush()
    resolver = CostResolver(db)
    for i, l in enumerate(lines, 1):
        line = QuotationLine(quotation_id=q.id, position=i, **l.model_dump())
        _price_line(db, ctx, q, line, resolver)
        db.add(line)
        db.flush()
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
    apply_changes(q, data)
    if "price_list_id" in data:
        get_or_404(db, PriceList, q.price_list_id)
        resolver = CostResolver(db)
        for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)):
            _price_line(db, ctx, q, line, resolver)
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
    count = len(list(db.scalars(select(QuotationLine.id).where(QuotationLine.quotation_id == q.id))))
    line = QuotationLine(quotation_id=q.id, position=count + 1, **body.model_dump())
    _price_line(db, ctx, q, line, CostResolver(db))
    db.add(line)
    db.flush()
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
    _price_line(db, ctx, q, line, CostResolver(db))
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
    before = snapshot(line)
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
    before = snapshot(q)
    q.status = body.status
    audit(db, q, "update", before)
    db.commit()
    return _quote_out(db, q, with_calc=False)


@router.post("/quotations/{quote_id}/recalculate", response_model=QuotationOut)
def recalculate(quote_id: uuid.UUID, dc=Depends(require("quotes.write"))):
    """Re-run every line with the CURRENT published formulas and prices (explicit action)."""
    db, ctx = dc
    q = _get_quote(db, ctx, quote_id, "quotes.write")
    if q.status not in EDITABLE:
        raise Conflict("Quotation is locked", code="QUOTE_LOCKED")
    resolver = CostResolver(db)
    for line in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)):
        _price_line(db, ctx, q, line, resolver)
    _totals(db, q)
    db.commit()
    return _quote_out(db, q)
