"""HR settings for pay and attendance: pay policies, work zones, public holidays, decisions on single days, the
punch from the phone app, the monthly attendance review, and allowing a commission under the minimum."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.api.common import DeleteResult, Record, VersionedUpdate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.core.pii import log_pii
from app.db.base import utcnow
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.deletions.router import deletable
from app.modules.hr.models import (AttendanceDay, AttendancePunch, Employee, PayPolicy, PayrollRun, Payslip,
                                   PublicHoliday, WorkZone)
from app.modules.hr.policy import LateTier, PieceRate, Rules, collections, commission, local_now, month_attendance
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(tags=["hr"])
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def _rules(raw: dict) -> dict:
    try:
        return Rules.model_validate(raw or {}).model_dump(mode="json")
    except ValidationError as e:
        raise ValidationFailed("The policy has a wrong value", code="POLICY_INVALID",
                               details={"errors": [{"field": ".".join(str(x) for x in err["loc"]), "msg": err["msg"]}
                                                   for err in e.errors()]})


# ================================================================ pay policies
class PolicyIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    rules: dict = Field(default_factory=dict)
    notes: str = ""


class PolicyUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=120)
    rules: dict | None = None
    notes: str | None = None


class PolicyOut(Record):
    code: str
    name: str
    rules: dict
    notes: str
    employees: int = 0


def _policy_out(db, p: PayPolicy) -> PolicyOut:
    out = PolicyOut.model_validate(p)
    out.rules = Rules.model_validate(p.rules or {}).model_dump(mode="json")
    out.employees = len(db.scalars(select(Employee.id).where(Employee.pay_policy_id == p.id,
                                                             Employee.deleted_at.is_(None))).all())
    return out


@router.get("/pay-policies", response_model=list[PolicyOut])
def list_policies(dc=Depends(require("hr.read"))):
    db, _ = dc
    return [_policy_out(db, p) for p in db.scalars(select(PayPolicy).where(PayPolicy.deleted_at.is_(None))
                                                   .order_by(PayPolicy.name))]


@router.get("/pay-policies/defaults")
def policy_defaults(dc=Depends(require("hr.read"))):
    """The fields of a policy and their starting values (for a new policy)."""
    return Rules().model_dump(mode="json")


@router.post("/pay-policies", response_model=PolicyOut, status_code=201)
def create_policy(body: PolicyIn, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    if db.scalar(select(PayPolicy.id).where(PayPolicy.code == body.code)):
        raise Conflict("A policy with this code exists", code="DUPLICATE_CODE")
    p = PayPolicy(code=body.code, name=body.name, rules=_rules(body.rules), notes=body.notes)
    db.add(p)
    db.flush()
    audit(db, p, "create")
    db.commit()
    return _policy_out(db, p)


@router.patch("/pay-policies/{policy_id}", response_model=PolicyOut)
def update_policy(policy_id: uuid.UUID, body: PolicyUpdate, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    p = get_or_404(db, PayPolicy, policy_id)
    check_version(p, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if "rules" in data:
        data["rules"] = _rules(data["rules"])
    before = snapshot(p)
    apply_changes(p, data)
    audit(db, p, "update", before)
    db.commit()
    return _policy_out(db, p)


@deletable(router, "/pay-policies/{policy_id}", "pay-policies", ("سياسة مرتبات", PayPolicy, "name"))
def delete_policy(policy_id: uuid.UUID, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    p = get_or_404(db, PayPolicy, policy_id)
    if db.scalar(select(Employee.id).where(Employee.pay_policy_id == p.id, Employee.deleted_at.is_(None))):
        raise Conflict("Employees follow this policy: move them to another first", code="POLICY_IN_USE")
    before = snapshot(p)
    p.deleted_at = utcnow()
    audit(db, p, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


# The company's papers (WINTAG, Nov 2026) as starting policies: created once on request, then edited freely.
def _templates() -> list[tuple[str, str, Rules]]:
    office = Rules(work_start="09:00", work_end="17:00", weekly_off=[4], late_grace_minutes=30,
                   late_tiers=[LateTier(from_minutes=31, action="day_fraction", value=Decimal("0.5"))],
                   permissions_per_month=2, permission_max_minutes=120,
                   absence_notified_days=Decimal(1), absence_unnotified_days=Decimal(2), absence_repeat_doubles=True)
    sales = office.model_copy(update={"commission_rate": Decimal("0.01"),
                                      "commission_min_collections": Decimal(300000)})
    factory = Rules(work_start="09:00", work_end="18:00", weekly_off=[4],
                    late_tiers=[LateTier(from_minutes=1, to_minutes=59, action="compensate"),
                                LateTier(from_minutes=60, action="multiplier", value=Decimal("1.5"))],
                    overtime_enabled=True, overtime_after="end", overtime_multiplier=Decimal("1.5"),
                    travel_day_value=Decimal("1.5"), travel_meal=Decimal(125))
    install = Rules(work_start="09:00", work_end="18:00", weekly_off=[4],
                    late_tiers=[LateTier(from_minutes=1, action="multiplier", value=Decimal("1.5"))],
                    absence_notified_days=Decimal(1), absence_unnotified_days=Decimal(2),
                    absence_install_day_days=Decimal(3),
                    overtime_enabled=True, overtime_after="hours", overtime_after_hours=Decimal(9),
                    overtime_multiplier=Decimal("1.5"), field_days_flexible=True, field_day_hours=Decimal(9),
                    travel_day_value=Decimal(1), travel_meal=Decimal(125), install_transport_by_zone=True,
                    holiday_day_value=Decimal(2), app_punch=True,
                    piece_rates=[PieceRate(name="شاتر - فتحة عادية", rate=Decimal(400)),
                                 PieceRate(name="زنكالوم / هارد فوم - فتحة", rate=Decimal(600))])
    return [("OFFICE", "الإدارة", office), ("SALES", "المبيعات", sales), ("FACTORY", "المصنع", factory),
            ("INSTALL", "التركيبات", install)]


ZONES = [("القاهرة", "30.044420", "31.235712", "25"), ("الجيزة", "30.013056", "31.208853", "20"),
         ("العاشر من رمضان", "30.296700", "31.743300", "12"), ("العبور", "30.228300", "31.479400", "8")]


@router.post("/pay-policies/templates", response_model=list[PolicyOut])
def create_templates(dc=Depends(require("hr.payroll"))):
    """Starting policies (الإدارة، المبيعات، المصنع، التركيبات) and zones (القاهرة، الجيزة، العاشر، العبور), only
    those the company does not have yet. Everything in them is editable afterwards."""
    db, _ = dc
    have = set(db.scalars(select(PayPolicy.code)))
    for code, name, rules in _templates():
        if code not in have:
            p = PayPolicy(code=code, name=name, rules=rules.model_dump(mode="json"), notes="")
            db.add(p)
            db.flush()
            audit(db, p, "create", note="من نموذج")
    if not db.scalar(select(WorkZone.id)):
        for name, lat, lon, km in ZONES:
            z = WorkZone(name=name, latitude=Decimal(lat), longitude=Decimal(lon), radius_km=Decimal(km),
                         transport_allowance=Decimal(0), is_active=True)
            db.add(z)
            db.flush()
            audit(db, z, "create", note="من نموذج")
    db.commit()
    return list_policies((db, _))


# ================================================================ zones
class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    radius_km: Decimal = Field(gt=0, le=500)
    transport_allowance: Decimal = Field(Decimal(0), ge=0)
    is_active: bool = True


class ZoneUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=120)
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)
    radius_km: Decimal | None = Field(None, gt=0, le=500)
    transport_allowance: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None


class ZoneOut(Record):
    name: str
    latitude: Decimal
    longitude: Decimal
    radius_km: Decimal
    transport_allowance: Decimal
    is_active: bool


@router.get("/work-zones", response_model=list[ZoneOut])
def list_zones(dc=Depends(require("hr.read"))):
    db, _ = dc
    return db.scalars(select(WorkZone).order_by(WorkZone.name)).all()


@router.post("/work-zones", response_model=ZoneOut, status_code=201)
def create_zone(body: ZoneIn, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    z = WorkZone(**body.model_dump())
    db.add(z)
    db.flush()
    audit(db, z, "create")
    db.commit()
    return z


@router.patch("/work-zones/{zone_id}", response_model=ZoneOut)
def update_zone(zone_id: uuid.UUID, body: ZoneUpdate, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    z = get_or_404(db, WorkZone, zone_id)
    check_version(z, body.version)
    before = snapshot(z)
    apply_changes(z, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, z, "update", before)
    db.commit()
    return z


@deletable(router, "/work-zones/{zone_id}", "work-zones", ("منطقة", WorkZone, "name"))
def delete_zone(zone_id: uuid.UUID, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    z = get_or_404(db, WorkZone, zone_id)
    audit(db, z, "delete", snapshot(z))
    db.delete(z)
    db.commit()
    return DeleteResult(result="deleted")


# ================================================================ public holidays
class HolidayIn(BaseModel):
    day: date
    name: str = Field("", max_length=120)


class HolidayOut(Record):
    day: date
    name: str


@router.get("/public-holidays", response_model=list[HolidayOut])
def list_holidays(year: int | None = None, dc=Depends(require("hr.read"))):
    db, _ = dc
    year = year or date.today().year
    return db.scalars(select(PublicHoliday).where(PublicHoliday.day.between(date(year, 1, 1), date(year, 12, 31)))
                      .order_by(PublicHoliday.day)).all()


@router.post("/public-holidays", response_model=HolidayOut, status_code=201)
def create_holiday(body: HolidayIn, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    if db.scalar(select(PublicHoliday.id).where(PublicHoliday.day == body.day)):
        raise Conflict("This day is already a holiday", code="DUPLICATE_DAY")
    h = PublicHoliday(day=body.day, name=body.name)
    db.add(h)
    db.flush()
    audit(db, h, "create")
    db.commit()
    return h


@deletable(router, "/public-holidays/{holiday_id}", "public-holidays", ("إجازة رسمية", PublicHoliday, "name"))
def delete_holiday(holiday_id: uuid.UUID, dc=Depends(require("hr.payroll"))):
    db, _ = dc
    h = get_or_404(db, PublicHoliday, holiday_id)
    audit(db, h, "delete", snapshot(h))
    db.delete(h)
    db.commit()
    return DeleteResult(result="deleted")


# ================================================================ one employee's month, day decisions
def _employee(db, ctx, eid, permission="hr.read") -> Employee:
    e = get_or_404(db, Employee, eid)
    ctx.require(permission, e.branch_id)
    return e


def _month(month: str) -> tuple[date, date]:
    import calendar

    y, m = int(month[:4]), int(month[5:])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _policy(db, e: Employee) -> Rules | None:
    p = db.get(PayPolicy, e.pay_policy_id) if e.pay_policy_id else None
    return Rules.model_validate(p.rules or {}) if p is not None and p.deleted_at is None else None


@router.get("/attendance/month")
def employee_month(employee_id: uuid.UUID, month: str = Query(pattern=MONTH), dc=Depends(require("hr.read"))):
    """Day by day: the kind, first and last punch, lateness, overtime, what is deducted / added, and what needs a
    look; with the totals and (for sales) the collections and the commission."""
    db, ctx = dc
    e = _employee(db, ctx, employee_id)
    rules = _policy(db, e)
    if rules is None:
        raise ValidationFailed("Give the employee a pay policy first", code="NO_POLICY")
    start, end = _month(month)
    att = month_attendance(db, e, rules, start, end)
    marks = {a.day.isoformat(): a for a in db.scalars(select(AttendanceDay).where(
        AttendanceDay.employee_id == e.id, AttendanceDay.day.between(start, end)))}
    for d in att["days"]:
        m = marks.get(d["day"])
        d["mark"] = None if m is None else {
            "id": str(m.id), "version": m.version, "kind": m.kind, "excuse": m.excuse,
            "permission_minutes": m.permission_minutes, "start_source": m.start_source, "note": m.note,
            "manual_in": m.manual_in.strftime("%H:%M") if m.manual_in else None,
            "manual_out": m.manual_out.strftime("%H:%M") if m.manual_out else None}
    collected = collections(db, e.id, start, end) if rules.commission_rate > 0 else Decimal(0)
    log_pii(db, ctx, "employee", [e.id], "view", ["full_name"])
    db.commit()
    return {**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in att.items()},
            "employee_id": str(e.id), "employee_name": e.full_name, "month": month,
            "collections": str(collected), "commission": str(commission(rules, collected, False)),
            "commission_min": str(rules.commission_min_collections)}


class DayMarkIn(BaseModel):
    kind: str | None = Field(None, pattern="^(normal|install|travel|off)$")
    excuse: str = Field("none", pattern="^(none|permission|notified|excused)$")
    permission_minutes: int = Field(0, ge=0, le=24 * 60)
    manual_in: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    manual_out: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    start_source: str | None = Field(None, pattern="^(device|app)$")
    note: str = ""
    version: int | None = None   # when changing an existing decision


def _hm(v: str | None) -> time | None:
    return time(int(v[:2]), int(v[3:])) if v else None


@router.put("/attendance/days/{employee_id}/{day}")
def mark_day(employee_id: uuid.UUID, day: date, body: DayMarkIn, dc=Depends(get_db_and_ctx)):
    """HR's decision on one day. The installations manager (field.manage) may only pick which morning punch
    counts when the device and the app both have one."""
    db, ctx = dc
    e = get_or_404(db, Employee, employee_id)
    full = ctx.can("hr.write", e.branch_id)
    if not full:
        ctx.require("field.manage", e.branch_id)
    m = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == e.id, AttendanceDay.day == day))
    if m is not None and body.version is not None:
        check_version(m, body.version)
    rules = _policy(db, e)
    if full and body.excuse == "permission" and rules is not None:
        if body.permission_minutes > rules.permission_max_minutes:
            raise ValidationFailed("Longer than a permission may be", code="PERMISSION_TOO_LONG",
                                   details={"max_minutes": rules.permission_max_minutes})
        start = day.replace(day=1)
        used = db.scalar(select(func.count()).select_from(AttendanceDay).where(
            AttendanceDay.employee_id == e.id, AttendanceDay.excuse == "permission", AttendanceDay.day != day,
            AttendanceDay.day >= start, AttendanceDay.day < (start + timedelta(days=32)).replace(day=1))) or 0
        if used >= rules.permissions_per_month:
            raise Conflict("No permissions left this month", code="PERMISSIONS_USED",
                           details={"per_month": rules.permissions_per_month})
    if m is None:
        m = AttendanceDay(employee_id=e.id, day=day, excuse="none", permission_minutes=0, conflict_notified=False,
                          note="")
        db.add(m)
        db.flush()
        before = None
    else:
        before = snapshot(m)
    if full:
        m.kind, m.excuse, m.permission_minutes = body.kind, body.excuse, body.permission_minutes
        m.manual_in, m.manual_out, m.note = _hm(body.manual_in), _hm(body.manual_out), body.note
    m.start_source = body.start_source
    audit(db, m, "update" if before else "create", before)
    db.commit()
    return {"id": str(m.id), "version": m.version}


# ================================================================ the phone app punch
class AppPunchIn(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    accuracy_m: Decimal | None = None


def _me(db, ctx) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.user_id == ctx.user_id, Employee.deleted_at.is_(None),
                                            Employee.status == "active"))


def _today_punches(db, e: Employee, now: datetime) -> list[AttendancePunch]:
    lo = datetime.combine(now.date(), time.min)
    return db.scalars(select(AttendancePunch).where(AttendancePunch.employee_id == e.id,
                                                    AttendancePunch.punched_at >= lo,
                                                    AttendancePunch.punched_at < lo + timedelta(days=1))
                      .order_by(AttendancePunch.punched_at)).all()


@router.get("/attendance/me")
def my_attendance(dc=Depends(get_db_and_ctx)):
    """For the phone: may this user punch from the app, and today's punches."""
    db, ctx = dc
    e = _me(db, ctx)
    rules = _policy(db, e) if e else None
    now = local_now()
    today = _today_punches(db, e, now) if e else []
    return {"can_punch": bool(rules and rules.app_punch),
            "punches": [{"at": p.punched_at.isoformat(), "source": p.source} for p in today]}


def warn_two_starts(db, ctx, e: Employee, day: date) -> None:
    """The device and the app both have a morning punch: the installations manager picks one (once)."""
    from app.modules.notifications.router import alert

    lo = datetime.combine(day, time.min)
    sources = set(db.scalars(select(AttendancePunch.source).where(
        AttendancePunch.employee_id == e.id, AttendancePunch.punched_at >= lo,
        AttendancePunch.punched_at < lo + timedelta(hours=13))))
    if len(sources) < 2:
        return
    m = db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == e.id, AttendanceDay.day == day))
    if m is not None and (m.conflict_notified or m.start_source):
        return
    if m is None:
        m = AttendanceDay(employee_id=e.id, day=day, excuse="none", permission_minutes=0, note="")
        db.add(m)
    m.conflict_notified = True
    alert(db, ctx, "field", e.branch_id, f"بصمتين بداية يوم {day.isoformat()}",
          f"{e.code}: فيه بصمة من الجهاز وبصمة من الموبايل. اختار واحدة منهم في مراجعة الحضور.",
          link=f"hr?tab=attendance&employee={e.id}&month={day.strftime('%Y-%m')}")


@router.post("/attendance/my-punch", status_code=201)
def app_punch(body: AppPunchIn, dc=Depends(get_db_and_ctx)):
    """بصمة من الموبايل: the time is the server's, the place is the phone's."""
    db, ctx = dc
    e = _me(db, ctx)
    rules = _policy(db, e) if e else None
    if not (rules and rules.app_punch):
        raise Forbidden("Your pay policy does not allow punching from the phone", code="APP_PUNCH_OFF")
    now = local_now().replace(microsecond=0)
    p = AttendancePunch(device_serial="APP", pin=e.attendance_pin or e.code[:20], employee_id=e.id, punched_at=now,
                        state=0, verify=0, source="app", latitude=body.latitude, longitude=body.longitude)
    db.add(p)
    db.flush()
    warn_two_starts(db, ctx, e, now.date())
    db.commit()
    return {"at": now.isoformat(), "punches": len(_today_punches(db, e, now))}


# ================================================================ commission under the minimum
class ForceIn(BaseModel):
    forced: bool


@router.post("/payslips/{slip_id}/commission")
def force_commission(slip_id: uuid.UUID, body: ForceIn, dc=Depends(require("hr.payroll"))):
    """The direct manager allowed the commission this month although the collections are under the minimum."""
    from app.modules.hr.router import _calculate, _run_out

    db, ctx = dc
    slip = get_or_404(db, Payslip, slip_id)
    run = get_or_404(db, PayrollRun, slip.run_id)
    ctx.require("hr.payroll", run.branch_id)
    if run.status != "draft":
        raise Conflict("A paid payroll is closed", code="PAYROLL_PAID")
    slip.commission_forced = body.forced
    db.flush()
    _calculate(db, run)
    run.version += 1
    audit(db, run, "update", None, note=("سماح بالعمولة " if body.forced else "إلغاء السماح بالعمولة ") + str(slip.employee_id))
    db.commit()
    return _run_out(db, ctx, run)
