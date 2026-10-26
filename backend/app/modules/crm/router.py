from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.common import DeleteResult, ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, NotFound
from app.core.numbering import next_number
from app.core.pii import log_pii
from app.db.base import utcnow
from app.modules.crm.models import Customer, SiteSurvey, SurveyOpening
from app.modules.org.models import Branch
from app.tenancy.context import require

router = APIRouter(tags=["crm"])

CUSTOMER_PII = list(Customer.__pii__)


def branch_scope(stmt, ctx, permission: str, column):
    """Limit a query to the branches where the user holds `permission`."""
    branches = ctx.branches_for(permission)
    if branches is None:
        return stmt
    nullable = column.property.columns[0].nullable
    return stmt.where(or_(column.in_(branches), column.is_(None)) if nullable else column.in_(branches))


def get_or_404(db, model, obj_id):
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise NotFound(f"{model.__name__} not found")
    return obj


# ---------------------------------------------------------------- customers
class CustomerIn(BaseModel):
    code: str | None = Field(None, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    customer_type: str = Field("end", pattern="^(end|dealer|contractor)$")
    phone: str | None = None
    phone2: str | None = None
    email: str | None = None
    address: str | None = None
    national_id: str | None = Field(None, max_length=20)
    tax_number: str | None = None
    branch_id: uuid.UUID | None = None
    price_list_id: uuid.UUID | None = None
    notes: str | None = None


class CustomerUpdate(VersionedUpdate):
    name: str | None = None
    customer_type: str | None = Field(None, pattern="^(end|dealer|contractor)$")
    phone: str | None = None
    phone2: str | None = None
    email: str | None = None
    address: str | None = None
    national_id: str | None = None
    tax_number: str | None = None
    branch_id: uuid.UUID | None = None
    price_list_id: uuid.UUID | None = None
    notes: str | None = None


class CustomerOut(Record):
    code: str
    name: str
    customer_type: str
    phone: str | None
    phone2: str | None
    email: str | None
    address: str | None
    national_id: str | None
    tax_number: str | None
    branch_id: uuid.UUID | None
    price_list_id: uuid.UUID | None
    notes: str | None
    anonymized: bool


@router.get("/customers", response_model=Page[CustomerOut])
def list_customers(q: str | None = None, customer_type: str | None = None, params: PageParams = Depends(),
                   dc=Depends(require("customers.read"))):
    db, ctx = dc
    stmt = select(Customer).where(Customer.deleted_at.is_(None)).order_by(Customer.name)
    stmt = branch_scope(stmt, ctx, "customers.read", Customer.branch_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.code.ilike(like), Customer.phone.ilike(like)))
    if customer_type:
        stmt = stmt.where(Customer.customer_type == customer_type)
    page = paginate(db, stmt, params, CustomerOut)
    log_pii(db, ctx, "customer", [c.id for c in page["items"]], "list", ["name", "phone"])
    db.commit()
    return page


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, dc=Depends(require("customers.create"))):
    db, ctx = dc
    if body.branch_id:
        ctx.require("customers.create", body.branch_id)
        get_or_404(db, Branch, body.branch_id)
    data = body.model_dump()
    data["code"] = data["code"] or next_number(db, "customer", "CU")
    if db.scalar(select(Customer).where(Customer.code == data["code"])):
        raise Conflict("Customer code exists", code="DUPLICATE_CODE")
    customer = Customer(**data)
    db.add(customer)
    db.flush()
    audit(db, customer, "create")
    log_pii(db, ctx, "customer", [customer.id], "create", [k for k in CUSTOMER_PII if data.get(k)])
    db.commit()
    return customer


def _visible_customer(db, ctx, customer_id, permission="customers.read") -> Customer:
    customer = get_or_404(db, Customer, customer_id)
    if customer.branch_id is not None:
        ctx.require(permission, customer.branch_id)
    return customer


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: uuid.UUID, dc=Depends(require("customers.read"))):
    db, ctx = dc
    customer = _visible_customer(db, ctx, customer_id)
    log_pii(db, ctx, "customer", [customer.id], "view", CUSTOMER_PII)
    db.commit()
    return customer


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: uuid.UUID, body: CustomerUpdate, dc=Depends(require("customers.write"))):
    db, ctx = dc
    customer = _visible_customer(db, ctx, customer_id, "customers.write")
    check_version(customer, body.version)
    before = snapshot(customer)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    apply_changes(customer, data)
    audit(db, customer, "update", before)
    log_pii(db, ctx, "customer", [customer.id], "update", [k for k in data if k in CUSTOMER_PII])
    db.commit()
    return customer


# ---------------------------------------------------------------- surveys
class OpeningIn(BaseModel):
    location: str = ""
    opening_width_mm: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    opening_height_mm: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    qty: int = Field(1, ge=1)
    model_id: uuid.UUID | None = None
    params: dict = {}
    color_code: str | None = None
    glass_material_code: str | None = None
    photo_id: uuid.UUID | None = None
    notes: str = ""
    total_height_mm: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    top_model_id: uuid.UUID | None = None      # arch (أرج) model; default: company setting
    unit_kind: str | None = Field(None, pattern="^(sliding|hinged)$")
    color_text: str | None = Field(None, max_length=80)
    glass_layers: str | None = Field(None, pattern="^(single|double)$")
    glass_color: str | None = Field(None, max_length=80)
    screen_type: str | None = Field(None, pattern="^(sliding|pleated|hinged|fixed)$")
    application: str = ""
    installation_method: str | None = Field(None, max_length=120)
    motor_type: str | None = Field(None, max_length=120)


class OpeningOut(ORMModel):
    id: uuid.UUID
    position: int
    location: str
    opening_width_mm: Decimal
    opening_height_mm: Decimal
    qty: int
    model_id: uuid.UUID | None
    params: dict
    color_code: str | None
    glass_material_code: str | None
    photo_id: uuid.UUID | None
    notes: str
    total_height_mm: Decimal | None
    top_model_id: uuid.UUID | None
    unit_kind: str | None
    color_text: str | None
    glass_layers: str | None
    glass_color: str | None
    screen_type: str | None
    application: str
    installation_method: str | None
    motor_type: str | None


SURVEY_KIND = "^(window|shutter)$"


class SurveyIn(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_date: date | None = None
    surveyor_id: uuid.UUID | None = None
    address: str | None = None
    notes: str = ""
    kind: str = Field("window", pattern=SURVEY_KIND)
    floor: str | None = Field(None, max_length=40)
    technician: str | None = Field(None, max_length=120)
    openings: list[OpeningIn] = []


class SurveyUpdate(VersionedUpdate):
    survey_date: date | None = None
    surveyor_id: uuid.UUID | None = None
    address: str | None = None
    status: str | None = Field(None, pattern="^(open|done|cancelled)$")
    notes: str | None = None
    kind: str | None = Field(None, pattern=SURVEY_KIND)
    floor: str | None = Field(None, max_length=40)
    technician: str | None = Field(None, max_length=120)
    openings: list[OpeningIn] | None = None


class SurveyOut(Record):
    number: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_date: date | None
    surveyor_id: uuid.UUID | None
    address: str | None
    status: str
    notes: str
    kind: str
    floor: str | None
    technician: str | None
    openings: list[OpeningOut] = []


def _survey_out(db, survey) -> SurveyOut:
    out = SurveyOut.model_validate(survey)
    out.openings = [OpeningOut.model_validate(o) for o in db.scalars(
        select(SurveyOpening).where(SurveyOpening.survey_id == survey.id).order_by(SurveyOpening.position))]
    return out


def _set_openings(db, survey, openings: list[OpeningIn]) -> None:
    for old in db.scalars(select(SurveyOpening).where(SurveyOpening.survey_id == survey.id)):
        db.delete(old)
    db.flush()
    for i, o in enumerate(openings, 1):
        db.add(SurveyOpening(survey_id=survey.id, position=i, **o.model_dump()))


@router.get("/surveys", response_model=Page[SurveyOut])
def list_surveys(customer_id: uuid.UUID | None = None, status: str | None = None, params: PageParams = Depends(),
                 dc=Depends(require("surveys.read"))):
    db, ctx = dc
    stmt = select(SiteSurvey).where(SiteSurvey.deleted_at.is_(None)).order_by(SiteSurvey.created_at.desc())
    stmt = branch_scope(stmt, ctx, "surveys.read", SiteSurvey.branch_id)
    if customer_id:
        stmt = stmt.where(SiteSurvey.customer_id == customer_id)
    if status:
        stmt = stmt.where(SiteSurvey.status == status)
    page = paginate(db, stmt, params, SurveyOut)
    by_survey: dict = {}
    if page["items"]:
        for o in db.scalars(select(SurveyOpening).where(SurveyOpening.survey_id.in_([s.id for s in page["items"]]))
                            .order_by(SurveyOpening.position)):
            by_survey.setdefault(o.survey_id, []).append(OpeningOut.model_validate(o))
    for item in page["items"]:
        item.openings = by_survey.get(item.id, [])
    return page


@router.post("/surveys", response_model=SurveyOut, status_code=201)
def create_survey(body: SurveyIn, dc=Depends(require("surveys.create"))):
    db, ctx = dc
    ctx.require("surveys.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    _visible_customer(db, ctx, body.customer_id)
    survey = SiteSurvey(number=next_number(db, "survey", "SV", branch.code),
                        **body.model_dump(exclude={"openings"}))
    db.add(survey)
    db.flush()
    _set_openings(db, survey, body.openings)
    audit(db, survey, "create")
    db.commit()
    return _survey_out(db, survey)


@router.get("/surveys/{survey_id}", response_model=SurveyOut)
def get_survey(survey_id: uuid.UUID, dc=Depends(require("surveys.read"))):
    db, ctx = dc
    survey = get_or_404(db, SiteSurvey, survey_id)
    ctx.require("surveys.read", survey.branch_id)
    if survey.address:
        log_pii(db, ctx, "customer", [survey.customer_id], "view", ["address"])
        db.commit()
    return _survey_out(db, survey)


@router.patch("/surveys/{survey_id}", response_model=SurveyOut)
def update_survey(survey_id: uuid.UUID, body: SurveyUpdate, dc=Depends(require("surveys.write"))):
    db, ctx = dc
    survey = get_or_404(db, SiteSurvey, survey_id)
    ctx.require("surveys.write", survey.branch_id)
    check_version(survey, body.version)
    before = snapshot(survey)
    data = body.model_dump(exclude_unset=True, exclude={"version", "openings"})
    if data.get("kind", "") is None:
        del data["kind"]
    apply_changes(survey, data)
    if body.openings is not None:
        _set_openings(db, survey, body.openings)
        survey.updated_at = utcnow()  # bump version when only the openings change
        db.flush()
    audit(db, survey, "update", before)
    db.commit()
    return _survey_out(db, survey)


# ---------------------------------------------------------------- delete (soft: history keeps pointing to them)
@router.delete("/customers/{customer_id}", response_model=DeleteResult)
def delete_customer(customer_id: uuid.UUID, dc=Depends(require("customers.delete"))):
    db, ctx = dc
    customer = _visible_customer(db, ctx, customer_id, "customers.delete")
    before = snapshot(customer)
    customer.deleted_at = utcnow()
    audit(db, customer, "delete", before)
    log_pii(db, ctx, "customer", [customer.id], "delete", ["name"])
    db.commit()
    return DeleteResult(result="deleted")


@router.delete("/surveys/{survey_id}", response_model=DeleteResult)
def delete_survey(survey_id: uuid.UUID, dc=Depends(require("surveys.delete"))):
    db, ctx = dc
    survey = get_or_404(db, SiteSurvey, survey_id)
    ctx.require("surveys.delete", survey.branch_id)
    before = snapshot(survey)
    survey.deleted_at = utcnow()
    audit(db, survey, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")
