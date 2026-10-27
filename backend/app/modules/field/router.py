"""Maintenance requests, technician jobs and GPS tracking.

The office assigns survey / installation / maintenance visits to technicians (users holding `field.self`).
The technician's phone (the MYTech mobile page, `/tech`) shows their jobs, moves each one along
(on the way -> arrived -> done) and sends GPS points only while a job is on the way or arrived:
no job, no tracking. The points are personal data: every read is logged and they are erased after
LOCATION_RETENTION_DAYS.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import any_, func, literal, select

from app.api.common import DeleteResult, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.maps import fill_location
from app.core.numbering import next_number
from app.core.pii import log_pii
from app.db.base import utcnow
from app.modules.crm.models import Customer, SiteSurvey
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.field.models import FieldJob, MaintenanceRequest, TechnicianLocation
from app.modules.org.models import Branch, Role, User, UserBranchRole
from app.modules.production.models import WorkOrder
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(tags=["field"])

JOB_KIND = "^(survey|installation|maintenance)$"
LOCATION_PII = ["latitude", "longitude"]


class _Place(BaseModel):
    address: str | None = None
    location_url: str | None = Field(None, max_length=2000)
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)


# ---------------------------------------------------------------- maintenance requests
class MaintenanceIn(_Place):
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    work_order_id: uuid.UUID | None = None
    request_date: date | None = None
    description: str = Field(min_length=1)
    cost: Decimal = Field(Decimal(0), ge=0)
    notes: str = ""


class MaintenanceUpdate(VersionedUpdate):
    description: str | None = None
    address: str | None = None
    location_url: str | None = Field(None, max_length=2000)
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)
    status: str | None = Field(None, pattern="^(open|scheduled|done|cancelled)$")
    cost: Decimal | None = Field(None, ge=0)
    notes: str | None = None
    work_order_id: uuid.UUID | None = None


class MaintenanceOut(Record):
    number: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    work_order_id: uuid.UUID | None
    request_date: date
    description: str
    address: str | None
    location_url: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    status: str
    cost: Decimal
    notes: str


def _maintenance(db, ctx, mid, permission) -> MaintenanceRequest:
    m = get_or_404(db, MaintenanceRequest, mid)
    ctx.require(permission, m.branch_id)
    return m


@router.get("/maintenance", response_model=Page[MaintenanceOut])
def list_maintenance(customer_id: uuid.UUID | None = None, status: str | None = None, params: PageParams = Depends(),
                     dc=Depends(require("maintenance.read"))):
    db, ctx = dc
    stmt = select(MaintenanceRequest).where(MaintenanceRequest.deleted_at.is_(None)) \
        .order_by(MaintenanceRequest.created_at.desc())
    stmt = branch_scope(stmt, ctx, "maintenance.read", MaintenanceRequest.branch_id)
    if customer_id:
        stmt = stmt.where(MaintenanceRequest.customer_id == customer_id)
    if status:
        stmt = stmt.where(MaintenanceRequest.status == status)
    return paginate(db, stmt, params, MaintenanceOut)


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
def create_maintenance(body: MaintenanceIn, dc=Depends(require("maintenance.create"))):
    db, ctx = dc
    ctx.require("maintenance.create", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    customer = get_or_404(db, Customer, body.customer_id)
    if body.work_order_id:
        wo = get_or_404(db, WorkOrder, body.work_order_id)
        if wo.customer_id != customer.id:
            raise ValidationFailed("Work order of another customer", code="WRONG_CUSTOMER")
    data = fill_location(body.model_dump(exclude={"request_date"}))
    if not data.get("address"):
        data["address"] = customer.address
    m = MaintenanceRequest(number=next_number(db, "maintenance", "MT", branch.code),
                           request_date=body.request_date or date.today(), **data)
    db.add(m)
    db.flush()
    audit(db, m, "create")
    from app.modules.notifications.router import alert
    for cat in ("sales", "field"):
        alert(db, ctx, cat, m.branch_id, f"طلب صيانة جديد {m.number}: {customer.name}", m.description[:200],
              f"customers/{customer.id}?tab=maintenance")
    db.commit()
    return m


@router.get("/maintenance/{mid}", response_model=MaintenanceOut)
def get_maintenance(mid: uuid.UUID, dc=Depends(require("maintenance.read"))):
    db, ctx = dc
    m = _maintenance(db, ctx, mid, "maintenance.read")
    log_pii(db, ctx, "customer", [m.customer_id], "view", ["address", "location"])
    db.commit()
    return m


@router.patch("/maintenance/{mid}", response_model=MaintenanceOut)
def update_maintenance(mid: uuid.UUID, body: MaintenanceUpdate, dc=Depends(require("maintenance.write"))):
    db, ctx = dc
    m = _maintenance(db, ctx, mid, "maintenance.write")
    check_version(m, body.version)
    before = snapshot(m)
    apply_changes(m, fill_location(body.model_dump(exclude_unset=True, exclude={"version"})))
    audit(db, m, "update", before)
    db.commit()
    return m


@router.delete("/maintenance/{mid}", response_model=DeleteResult)
def delete_maintenance(mid: uuid.UUID, dc=Depends(require("maintenance.delete"))):
    db, ctx = dc
    m = _maintenance(db, ctx, mid, "maintenance.delete")
    before = snapshot(m)
    m.deleted_at = utcnow()
    for job in db.scalars(select(FieldJob).where(FieldJob.maintenance_id == m.id, FieldJob.deleted_at.is_(None),
                                                 FieldJob.status.in_(("scheduled", "on_way", "arrived")))):
        job.status = "cancelled"
    audit(db, m, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


# ---------------------------------------------------------------- technician jobs
class JobIn(_Place):
    kind: str = Field(pattern=JOB_KIND)
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    technician_id: uuid.UUID
    scheduled_at: datetime
    survey_id: uuid.UUID | None = None
    work_order_id: uuid.UUID | None = None
    maintenance_id: uuid.UUID | None = None
    notes: str = ""


class JobUpdate(VersionedUpdate):
    technician_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    address: str | None = None
    location_url: str | None = Field(None, max_length=2000)
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)
    notes: str | None = None


class JobStatusIn(BaseModel):
    status: str = Field(pattern="^(on_way|arrived|done|cancelled)$")
    note: str = ""


class JobOut(Record):
    kind: str
    customer_id: uuid.UUID
    branch_id: uuid.UUID
    survey_id: uuid.UUID | None
    work_order_id: uuid.UUID | None
    maintenance_id: uuid.UUID | None
    technician_id: uuid.UUID
    scheduled_at: datetime
    status: str
    started_at: datetime | None
    arrived_at: datetime | None
    finished_at: datetime | None
    address: str | None
    location_url: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    notes: str
    result_note: str
    # for the technician's phone: who and where, without another request
    customer_name: str = ""
    customer_phone: str | None = None
    technician_name: str = ""
    reference: str = ""


def technician_ids(db) -> set[uuid.UUID]:
    """Users who hold `field.self` in any of their roles."""
    return set(db.scalars(select(UserBranchRole.user_id).join(Role, Role.id == UserBranchRole.role_id)
                          .where(literal("field.self") == any_(Role.permissions))))


def _job_out(db, job: FieldJob) -> JobOut:
    out = JobOut.model_validate(job)
    customer = db.get(Customer, job.customer_id)
    tech = db.get(User, job.technician_id)
    out.customer_name, out.customer_phone = (customer.name, customer.phone) if customer else ("", None)
    out.technician_name = tech.full_name if tech else ""
    ref = (db.get(SiteSurvey, job.survey_id) if job.survey_id else None) or \
          (db.get(WorkOrder, job.work_order_id) if job.work_order_id else None) or \
          (db.get(MaintenanceRequest, job.maintenance_id) if job.maintenance_id else None)
    out.reference = getattr(ref, "number", "") or ""
    return out


def _can_manage(ctx, branch_id) -> bool:
    return ctx.can("field.manage", branch_id)


def _job(db, ctx, job_id, *, manage: bool = False) -> FieldJob:
    job = get_or_404(db, FieldJob, job_id)
    if _can_manage(ctx, job.branch_id) or (not manage and ctx.can("field.read", job.branch_id)):
        return job
    if not manage and job.technician_id == ctx.user_id and ctx.can("field.self"):
        return job
    raise Forbidden("Not your job", code="FORBIDDEN", details={"permission": "field.manage"})


@router.get("/field/jobs", response_model=list[JobOut])
def list_jobs(technician_id: uuid.UUID | None = None, status: str | None = None, day: date | None = None,
              customer_id: uuid.UUID | None = None, mine: bool = False, dc=Depends(get_db_and_ctx)):
    """Office (field.read): every job, filtered. Technician (field.self): only their own (`mine`)."""
    db, ctx = dc
    stmt = select(FieldJob).where(FieldJob.deleted_at.is_(None)).order_by(FieldJob.scheduled_at)
    if mine or not ctx.can("field.read"):
        ctx.require("field.self")
        stmt = stmt.where(FieldJob.technician_id == ctx.user_id)
        if day is None and not status:   # the phone: what is open, plus what was done today
            today = datetime.combine(date.today(), datetime.min.time()).astimezone()
            stmt = stmt.where((FieldJob.status.in_(("scheduled", "on_way", "arrived"))) | (FieldJob.finished_at >= today))
    else:
        stmt = branch_scope(stmt, ctx, "field.read", FieldJob.branch_id)
    if technician_id:
        stmt = stmt.where(FieldJob.technician_id == technician_id)
    if status:
        stmt = stmt.where(FieldJob.status == status)
    if customer_id:
        stmt = stmt.where(FieldJob.customer_id == customer_id)
    if day:
        start = datetime.combine(day, datetime.min.time()).astimezone()
        stmt = stmt.where(FieldJob.scheduled_at >= start, FieldJob.scheduled_at < start + timedelta(days=1))
    return [_job_out(db, j) for j in db.scalars(stmt.limit(500))]


@router.post("/field/jobs", response_model=JobOut, status_code=201)
def create_job(body: JobIn, dc=Depends(require("field.manage"))):
    db, ctx = dc
    ctx.require("field.manage", body.branch_id)
    get_or_404(db, Branch, body.branch_id)
    customer = get_or_404(db, Customer, body.customer_id)
    if body.technician_id not in technician_ids(db):
        raise ValidationFailed("Not a technician", code="NOT_TECHNICIAN")
    data = fill_location(body.model_dump())
    source = None
    for key, model in (("survey_id", SiteSurvey), ("work_order_id", WorkOrder), ("maintenance_id", MaintenanceRequest)):
        if data.get(key):
            source = get_or_404(db, model, data[key])
            if source.customer_id != customer.id:
                raise ValidationFailed("Linked record of another customer", code="WRONG_CUSTOMER")
    # the place: as typed, else from the survey / maintenance request, else the customer's address
    if source is not None and not data.get("location_url") and getattr(source, "location_url", None):
        data.update(location_url=source.location_url, latitude=source.latitude, longitude=source.longitude)
    if not data.get("address"):
        data["address"] = getattr(source, "address", None) or customer.address
    job = FieldJob(**data)
    db.add(job)
    if isinstance(source, MaintenanceRequest) and source.status == "open":
        source.status = "scheduled"
    if isinstance(source, SiteSurvey):
        tech = db.get(User, body.technician_id)
        source.technician = tech.full_name if tech else source.technician
    db.flush()
    audit(db, job, "create")
    from app.modules.notifications.router import alert
    kind = JOB_NAMES.get(job.kind, job.kind)
    when = job.scheduled_at.strftime("%Y-%m-%d %H:%M")
    alert(db, ctx, "field", job.branch_id, f"مهمة {kind} جديدة: {customer.name}", when, "field?tab=jobs")
    alert(db, ctx, "field", job.branch_id, f"عندك مهمة {kind}: {customer.name}", f"{when} · {job.address or ''}", "field",
          users={job.technician_id})
    db.commit()
    return _job_out(db, job)


@router.patch("/field/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: uuid.UUID, body: JobUpdate, dc=Depends(require("field.manage"))):
    db, ctx = dc
    job = _job(db, ctx, job_id, manage=True)
    check_version(job, body.version)
    data = fill_location(body.model_dump(exclude_unset=True, exclude={"version"}))
    if data.get("technician_id") and data["technician_id"] not in technician_ids(db):
        raise ValidationFailed("Not a technician", code="NOT_TECHNICIAN")
    before = snapshot(job)
    apply_changes(job, data)
    audit(db, job, "update", before)
    db.commit()
    return _job_out(db, job)


JOB_NAMES = {"survey": "معاينة", "installation": "تركيب", "maintenance": "صيانة"}
NEXT = {"scheduled": {"on_way", "arrived", "cancelled"}, "on_way": {"arrived", "cancelled"},
        "arrived": {"done", "cancelled"}}


@router.post("/field/jobs/{job_id}/status", response_model=JobOut)
def job_status(job_id: uuid.UUID, body: JobStatusIn, dc=Depends(get_db_and_ctx)):
    """The technician (or the office) moves the job along: on the way -> arrived -> done."""
    db, ctx = dc
    job = _job(db, ctx, job_id)
    mine = job.technician_id == ctx.user_id and ctx.can("field.self")
    if not (mine or _can_manage(ctx, job.branch_id)):
        raise Forbidden("Not your job", code="FORBIDDEN", details={"permission": "field.manage"})
    if body.status == "cancelled" and not _can_manage(ctx, job.branch_id):
        raise Forbidden("Only the office cancels a job", code="FORBIDDEN", details={"permission": "field.manage"})
    if body.status not in NEXT.get(job.status, set()):
        raise Conflict(f"Cannot go from {job.status} to {body.status}", code="INVALID_TRANSITION")
    before = snapshot(job)
    now = utcnow()
    job.status = body.status
    if body.status == "on_way":
        job.started_at = now
    elif body.status == "arrived":
        job.arrived_at = now
        job.started_at = job.started_at or now
    elif body.status == "done":
        job.finished_at = now
        job.result_note = body.note or job.result_note
        if job.maintenance_id:
            m = db.get(MaintenanceRequest, job.maintenance_id)
            if m and m.status in ("open", "scheduled"):
                m.status = "done"
    if body.note and body.status != "done":
        job.notes = (job.notes + "\n" if job.notes else "") + body.note
    audit(db, job, "update", before)
    from app.modules.notifications.router import alert, customer_name
    tech = db.get(User, job.technician_id)
    word = {"on_way": "في الطريق لـ", "arrived": "وصل عند", "done": "خلص عند", "cancelled": "اتلغت مهمته عند"}
    text = f"{tech.full_name if tech else 'الفني'} {word.get(job.status, job.status)} {customer_name(db, job.customer_id)}"
    alert(db, ctx, "field", job.branch_id, text, body.note or "", "field?tab=jobs")
    if job.status == "done" and job.kind == "installation":
        alert(db, ctx, "sales", job.branch_id, f"التركيب خلص عند {customer_name(db, job.customer_id)}", body.note or "",
              f"customers/{job.customer_id}")
    db.commit()
    return _job_out(db, job)


@router.delete("/field/jobs/{job_id}", response_model=DeleteResult)
def delete_job(job_id: uuid.UUID, dc=Depends(require("field.delete"))):
    db, ctx = dc
    job = get_or_404(db, FieldJob, job_id)
    ctx.require("field.delete", job.branch_id)
    before = snapshot(job)
    job.deleted_at = utcnow()
    audit(db, job, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


# ---------------------------------------------------------------- GPS
class LocationIn(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    accuracy_m: Decimal | None = Field(None, ge=0, le=100000)


@router.post("/field/locations", status_code=201)
def send_location(body: LocationIn, dc=Depends(require("field.self"))):
    """From the technician's phone. Accepted only while one of their jobs is on the way or arrived."""
    db, ctx = dc
    job = db.scalar(select(FieldJob).where(FieldJob.technician_id == ctx.user_id, FieldJob.deleted_at.is_(None),
                                           FieldJob.status.in_(("on_way", "arrived")))
                    .order_by(FieldJob.started_at.desc().nulls_last()).limit(1))
    if job is None:
        raise Conflict("No job in progress: location is not recorded", code="NO_ACTIVE_JOB")
    six = Decimal("0.000001")
    db.add(TechnicianLocation(user_id=ctx.user_id, job_id=job.id, latitude=body.latitude.quantize(six),
                              longitude=body.longitude.quantize(six),
                              accuracy_m=body.accuracy_m.quantize(Decimal("0.1")) if body.accuracy_m is not None else None))
    db.commit()
    return {"job_id": str(job.id)}


class PointOut(BaseModel):
    at: datetime
    latitude: Decimal
    longitude: Decimal
    accuracy_m: Decimal | None = None


class TechnicianOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    last: PointOut | None = None
    active_job: JobOut | None = None
    jobs_today: int = 0


@router.get("/field/technicians", response_model=list[TechnicianOut])
def technicians(dc=Depends(require("field.read"))):
    """Every technician with their last position (if on a job now) and current job: the map."""
    db, ctx = dc
    ids = technician_ids(db)
    users = db.scalars(select(User).where(User.id.in_(ids), User.is_active, User.deleted_at.is_(None))
                       .order_by(User.full_name)).all()
    today = datetime.combine(date.today(), datetime.min.time()).astimezone()
    out = []
    for u in users:
        t = TechnicianOut(user_id=u.id, full_name=u.full_name)
        job = db.scalar(select(FieldJob).where(FieldJob.technician_id == u.id, FieldJob.deleted_at.is_(None),
                                               FieldJob.status.in_(("on_way", "arrived"))).limit(1))
        if job is not None:
            t.active_job = _job_out(db, job)
            last = db.scalar(select(TechnicianLocation).where(TechnicianLocation.user_id == u.id)
                             .order_by(TechnicianLocation.at.desc()).limit(1))
            if last is not None:
                t.last = PointOut(at=last.at, latitude=last.latitude, longitude=last.longitude,
                                  accuracy_m=last.accuracy_m)
        t.jobs_today = db.scalar(select(func.count()).select_from(FieldJob).where(
            FieldJob.technician_id == u.id, FieldJob.deleted_at.is_(None), FieldJob.scheduled_at >= today,
            FieldJob.scheduled_at < today + timedelta(days=1))) or 0
        out.append(t)
    shown = [t.user_id for t in out if t.last]
    if shown:
        log_pii(db, ctx, "user", shown, "view", LOCATION_PII)
        db.commit()
    return out


@router.get("/field/jobs/{job_id}/track", response_model=list[PointOut])
def job_track(job_id: uuid.UUID, dc=Depends(require("field.read"))):
    """The technician's path during one job."""
    db, ctx = dc
    job = get_or_404(db, FieldJob, job_id)
    ctx.require("field.read", job.branch_id)
    points = db.scalars(select(TechnicianLocation).where(TechnicianLocation.job_id == job.id)
                        .order_by(TechnicianLocation.at).limit(5000)).all()
    if points:
        log_pii(db, ctx, "user", [job.technician_id], "view", LOCATION_PII)
        db.commit()
    return [PointOut(at=p.at, latitude=p.latitude, longitude=p.longitude, accuracy_m=p.accuracy_m) for p in points]


@router.get("/field/technician-users", response_model=list[dict])
def technician_users(dc=Depends(get_db_and_ctx)):
    """Names for the "assign to" picker."""
    db, ctx = dc
    if not (ctx.can("field.manage") or ctx.can("field.read")):
        ctx.require("field.manage")
    ids = technician_ids(db)
    return [{"id": str(u.id), "full_name": u.full_name} for u in db.scalars(
        select(User).where(User.id.in_(ids), User.is_active, User.deleted_at.is_(None)).order_by(User.full_name))]


def purge_old_locations(db, days: int) -> int:
    """Called daily by the scheduler (system session): erase GPS points older than the retention period."""
    from sqlalchemy import delete

    result = db.execute(delete(TechnicianLocation).where(TechnicianLocation.at < utcnow() - timedelta(days=days)))
    return result.rowcount or 0
