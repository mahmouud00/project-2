"""المشاريع: one customer's job in phases. A phase is a quotation of its own (its sizes and price), made into a work
order of its own (its cutting, its goods orders); the project shows them together and adds them up.

From a quotation, «مرحلة جديدة» starts the next phase: a new empty quotation for the same customer in the same
project (the project is made on the first phase, named after the customer, and can be renamed)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.common import Record, VersionedUpdate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import ValidationFailed
from app.core.numbering import next_number
from app.core.pii import log_pii
from app.modules.crm.models import Customer
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.org.models import Branch
from app.modules.sales.models import Project, Quotation
from app.tenancy.context import require

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    notes: str = ""


class ProjectUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = None


class PhaseOut(BaseModel):
    quotation_id: uuid.UUID
    quotation_number: str
    phase_name: str | None
    status: str
    issue_date: date | None
    total: Decimal
    lines: int
    work_order_id: uuid.UUID | None = None
    work_order_number: str | None = None
    stage: str | None = None
    wo_total: Decimal | None = None
    paid: Decimal | None = None


class ProjectOut(Record):
    number: str
    name: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    notes: str
    customer_name: str = ""
    phases: list[PhaseOut] = []
    quoted_total: Decimal = Decimal(0)       # every phase not rejected / expired
    ordered_total: Decimal = Decimal(0)      # phases made into work orders
    paid: Decimal = Decimal(0)
    remaining: Decimal = Decimal(0)


def _out(db, p: Project) -> ProjectOut:
    from app.modules.production.models import WorkOrder
    from app.modules.sales.models import QuotationLine

    out = ProjectOut.model_validate(p)
    c = db.get(Customer, p.customer_id)
    out.customer_name = c.name if c else ""
    quotes = db.scalars(select(Quotation).where(Quotation.project_id == p.id, Quotation.deleted_at.is_(None))
                        .order_by(Quotation.created_at)).all()
    for q in quotes:
        n = db.scalar(select(func.count()).select_from(QuotationLine).where(
            QuotationLine.quotation_id == q.id, QuotationLine.parent_line_id.is_(None))) or 0
        ph = PhaseOut(quotation_id=q.id, quotation_number=q.number, phase_name=q.phase_name, status=q.status,
                      issue_date=q.issue_date, total=q.total, lines=n)
        wo = db.scalar(select(WorkOrder).where(WorkOrder.quotation_id == q.id, WorkOrder.deleted_at.is_(None),
                                               WorkOrder.stage != "cancelled"))
        if wo is not None:
            ph.work_order_id, ph.work_order_number, ph.stage = wo.id, wo.number, wo.stage
            ph.wo_total, ph.paid = wo.total, wo.paid_amount
            out.ordered_total += wo.total
            out.paid += wo.paid_amount
        if q.status not in ("rejected", "expired"):
            out.quoted_total += q.total
        out.phases.append(ph)
    out.remaining = out.ordered_total - out.paid
    return out


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(customer_id: uuid.UUID | None = None, dc=Depends(require("quotes.read"))):
    db, ctx = dc
    stmt = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.created_at.desc())
    stmt = branch_scope(stmt, ctx, "quotes.read", Project.branch_id)
    if customer_id:
        stmt = stmt.where(Project.customer_id == customer_id)
    rows = db.scalars(stmt.limit(200)).all()
    log_pii(db, ctx, "customer", {p.customer_id for p in rows}, "list", ["name"])
    db.commit()
    return [_out(db, p) for p in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, dc=Depends(require("quotes.read"))):
    db, ctx = dc
    p = get_or_404(db, Project, project_id)
    ctx.require("quotes.read", p.branch_id)
    log_pii(db, ctx, "customer", [p.customer_id], "view", ["name"])
    db.commit()
    return _out(db, p)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, dc=Depends(require("quotes.create"))):
    db, ctx = dc
    ctx.require("quotes.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    get_or_404(db, Customer, body.customer_id)
    p = Project(number=next_number(db, "project", "PJ", branch.code), name=body.name, customer_id=body.customer_id,
                branch_id=branch.id, notes=body.notes)
    db.add(p)
    db.flush()
    audit(db, p, "create")
    db.commit()
    return _out(db, p)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: uuid.UUID, body: ProjectUpdate, dc=Depends(require("quotes.write"))):
    db, ctx = dc
    p = get_or_404(db, Project, project_id)
    ctx.require("quotes.write", p.branch_id)
    check_version(p, body.version)
    before = snapshot(p)
    apply_changes(p, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, p, "update", before)
    db.commit()
    return _out(db, p)


def ensure_project(db, q: Quotation, name: str | None = None) -> Project:
    """The quotation's project; made on its first phase (named after the customer)."""
    from app.modules.production.models import WorkOrder

    if q.project_id:
        return db.get(Project, q.project_id)
    customer = db.get(Customer, q.customer_id)
    branch = db.get(Branch, q.branch_id)
    p = Project(number=next_number(db, "project", "PJ", branch.code),
                name=(name or "").strip() or f"مشروع {customer.name if customer else ''}".strip(),
                customer_id=q.customer_id, branch_id=q.branch_id, notes="")
    db.add(p)
    db.flush()
    audit(db, p, "create")
    q.project_id = p.id
    q.phase_name = q.phase_name or "المرحلة 1"
    for wo in db.scalars(select(WorkOrder).where(WorkOrder.quotation_id == q.id)):
        wo.project_id = p.id
    return p


class PhaseIn(BaseModel):
    phase_name: str | None = Field(None, max_length=120)
    project_name: str | None = Field(None, max_length=200)   # when the project is made now


@router.post("/quotations/{quote_id}/phase")
def new_phase(quote_id: uuid.UUID, body: PhaseIn, dc=Depends(require("quotes.create"))):
    """مرحلة جديدة: a new empty quotation for the same customer, in the same project, with its own sizes."""
    from app.modules.sales.router import QuotationIn, create_quotation

    db, ctx = dc
    q = get_or_404(db, Quotation, quote_id)
    ctx.require("quotes.create", q.branch_id)
    if q.deleted_at is not None:
        raise ValidationFailed("Quotation was deleted", code="QUOTE_DELETED")
    p = ensure_project(db, q, body.project_name)
    count = db.scalar(select(func.count()).select_from(Quotation).where(
        Quotation.project_id == p.id, Quotation.deleted_at.is_(None))) or 0
    db.flush()
    db.commit()
    out = create_quotation(QuotationIn(customer_id=q.customer_id, branch_id=q.branch_id, tax_pct=q.tax_pct,
                                       terms=q.terms, salesperson_id=q.salesperson_id), (db, ctx))
    new = db.get(Quotation, out.id)
    new.project_id = p.id
    new.phase_name = (body.phase_name or "").strip() or f"المرحلة {count + 1}"
    audit(db, new, "update", note=f"مرحلة من مشروع {p.number}")
    db.commit()
    return {"id": str(new.id), "number": new.number, "project_id": str(p.id), "phase_name": new.phase_name}


class AttachIn(BaseModel):
    project_id: uuid.UUID | None = None
    phase_name: str | None = Field(None, max_length=120)


@router.put("/quotations/{quote_id}/project")
def attach_quote(quote_id: uuid.UUID, body: AttachIn, dc=Depends(require("quotes.write"))):
    """Put an existing quotation (and its work order) in a project of the same customer, or take it out."""
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    q = get_or_404(db, Quotation, quote_id)
    ctx.require("quotes.write", q.branch_id)
    if body.project_id:
        p = get_or_404(db, Project, body.project_id)
        if p.customer_id != q.customer_id:
            raise ValidationFailed("The project is another customer's", code="PROJECT_CUSTOMER")
    before = snapshot(q)
    q.project_id = body.project_id
    q.phase_name = (body.phase_name or "").strip() or (q.phase_name if body.project_id else None)
    for wo in db.scalars(select(WorkOrder).where(WorkOrder.quotation_id == q.id)):
        wo.project_id = body.project_id
    audit(db, q, "update", before)
    db.commit()
    return {"id": str(q.id), "project_id": str(q.project_id) if q.project_id else None, "phase_name": q.phase_name}
