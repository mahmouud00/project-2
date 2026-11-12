"""سياسات المرتبات والحضور: how one employee's month is worked out from their punches.

Every number is the company's own (PayPolicy.rules, edited in HR → «سياسات المرتبات»); nothing here is a company
rule. A policy says the working hours, the weekly day off, how lateness is answered (tiers by minutes late: a
fraction of a day, the minutes times a factor, or «stay after the end as long as you were late»), what an absence
costs (with / without notice, doubling when repeated, on an installation day), overtime, travel / installation days
(by where the job is: inside one of the company's zones or outside them all), work on a day off, the sales
commission on collections, and piece rates for temporary workers.

A day's kind: off (weekly day off / public holiday), leave (approved leave), install / travel (a field job that day:
inside a zone / outside them all), normal. HR can change any day (AttendanceDay): its kind, an excuse (إذن,
غياب بتبليغ, معذور), times by hand, and which morning punch counts when the device and the phone app both have one.

Attendance counts from the employee's first punch ever: before that (the device was not there yet) nothing is
deducted. Today and later days are not counted until they have punches.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select

CENT = Decimal("0.01")
TZ = "Africa/Cairo"
_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class LateTier(BaseModel):
    """Lateness from `from_minutes` to `to_minutes` (empty: and more) after the start of work."""
    from_minutes: int = Field(1, ge=0)
    to_minutes: int | None = Field(None, ge=0)
    action: Literal["day_fraction", "multiplier", "compensate", "none"] = "multiplier"
    value: Decimal = Field(Decimal(1), ge=0)   # day_fraction: of a day · multiplier: × the minutes late


class PieceRate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rate: Decimal = Field(ge=0)


class Rules(BaseModel):
    # working day
    work_start: str = Field("09:00", pattern=_HHMM)
    work_end: str = Field("17:00", pattern=_HHMM)
    weekly_off: list[int] = Field(default_factory=lambda: [4])   # 0 Monday … 4 Friday … 6 Sunday
    day_divisor: Decimal = Field(Decimal(30), gt=0)               # a day's pay = salary ÷ this
    # lateness
    late_grace_minutes: int = Field(0, ge=0)
    late_tiers: list[LateTier] = Field(default_factory=list)
    # permissions (إذن): how many a month and how long each
    permissions_per_month: int = Field(2, ge=0)
    permission_max_minutes: int = Field(120, ge=0)
    # absence (in days of pay)
    absence_notified_days: Decimal = Field(Decimal(1), ge=0)
    absence_unnotified_days: Decimal = Field(Decimal(2), ge=0)
    absence_repeat_doubles: bool = False               # unnotified: 2, then 4, then 8 … in the same month
    absence_install_day_days: Decimal | None = Field(None, ge=0)   # absent on a day with a field job, even notified
    # overtime
    overtime_enabled: bool = False
    overtime_after: Literal["end", "hours"] = "end"    # after the end of work / after so many hours of work
    overtime_after_hours: Decimal = Field(Decimal(9), gt=0)
    overtime_multiplier: Decimal = Field(Decimal("1.5"), ge=0)
    # field days (installation / travel)
    field_days_flexible: bool = False                   # the day starts when the work starts: no lateness
    field_day_hours: Decimal = Field(Decimal(9), gt=0)  # net hours of a field day (overtime after them)
    travel_day_value: Decimal = Field(Decimal(1), ge=0) # a travel day is paid as so many days
    travel_meal: Decimal = Field(Decimal(0), ge=0)      # and a meal allowance
    install_transport_by_zone: bool = False             # an installation day inside a zone: that zone's transport
    holiday_day_value: Decimal = Field(Decimal(2), ge=0)   # working on the day off / a public holiday
    app_punch: bool = False                             # may punch from the phone (with the place)
    # sales commission on collections
    commission_rate: Decimal = Field(Decimal(0), ge=0, le=1)          # 0.01 = 1%
    commission_min_collections: Decimal = Field(Decimal(0), ge=0)     # below it: none, unless the manager allows
    # temporary workers
    piece_rates: list[PieceRate] = Field(default_factory=list)

    @field_validator("weekly_off")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekday 0..6")
        return sorted(set(v))


def hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def work_minutes(r: Rules) -> int:
    s, e = hm(r.work_start), hm(r.work_end)
    return max((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute), 1)


def rates(r: Rules, salary: Decimal) -> tuple[Decimal, Decimal]:
    """(a day's pay, an hour's pay)."""
    day = Decimal(salary) / r.day_divisor
    return day, day * 60 / work_minutes(r)


# ------------------------------------------------------------------ zones
def distance_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def zone_of(zones, lat, lon):
    """The zone a place is in (the nearest when several), or None: outside all = travel."""
    best = None
    for z in zones:
        d = distance_km(lat, lon, z.latitude, z.longitude)
        if d <= float(z.radius_km) and (best is None or d < best[0]):
            best = (d, z)
    return best[1] if best else None


# ------------------------------------------------------------------ one day
def _late(r: Rules, late: int) -> tuple[Decimal, int, bool]:
    """(day fraction, minutes to deduct, compensate?) for `late` minutes."""
    if late <= r.late_grace_minutes:
        return Decimal(0), 0, False
    for t in r.late_tiers:
        if late >= t.from_minutes and (t.to_minutes is None or late <= t.to_minutes):
            if t.action == "day_fraction":
                return t.value, 0, False
            if t.action == "multiplier":
                return Decimal(0), int((Decimal(late) * t.value).to_integral_value(ROUND_HALF_UP)), False
            if t.action == "compensate":
                return Decimal(0), 0, True
            return Decimal(0), 0, False
    return Decimal(0), 0, False


def day_result(r: Rules, d: date, kind: str, first: datetime | None, last: datetime | None,
               excuse: str = "none", permission_minutes: int = 0) -> dict:
    """The attendance numbers of one day that has punches (first / last), by its kind."""
    out = {"late": 0, "late_day": Decimal(0), "late_cut": 0, "overtime": 0, "worked": 0}
    if first is None:
        return out
    start, end = datetime.combine(d, hm(r.work_start)), datetime.combine(d, hm(r.work_end))
    if last is not None and last > first:
        out["worked"] = minutes(first, last)
    flexible = kind in ("install", "travel") and r.field_days_flexible
    stayed_for_late = 0
    if kind == "normal" or (kind in ("install", "travel") and not flexible):
        late = max(minutes(start, first), 0) - (permission_minutes if excuse == "permission" else 0)
        late = max(late, 0)
        if excuse == "excused":
            late = 0
        out["late"] = late
        frac, cut, compensate = _late(r, late)
        out["late_day"] = frac
        if compensate:
            stayed = max(minutes(end, last), 0) if last is not None else 0
            stayed_for_late = min(stayed, late)
            cut = late - stayed_for_late       # what was not made up is deducted minute for minute
        out["late_cut"] = cut
    if r.overtime_enabled and last is not None and kind != "off":
        if flexible or r.overtime_after == "hours":
            limit = int((r.field_day_hours if flexible else r.overtime_after_hours) * 60)
            out["overtime"] = max(out["worked"] - limit, 0)
        else:
            out["overtime"] = max(minutes(end, last) - stayed_for_late, 0)
    return out


# ------------------------------------------------------------------ one employee's month
def local_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)


def local_date(dt: datetime) -> date:
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(ZoneInfo(TZ)).date()


def month_attendance(db, employee, rules: Rules, start: date, end: date) -> dict:
    """Day by day and totals for one employee between start and end (a month)."""
    from app.modules.field.models import FieldJob
    from app.modules.hr.models import AttendanceDay, AttendancePunch, Leave, PublicHoliday, WorkZone

    today = local_now().date()
    first_ever = db.scalar(select(func.min(AttendancePunch.punched_at)).where(
        AttendancePunch.employee_id == employee.id))
    track_from = first_ever.date() if first_ever else None
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end + timedelta(days=1), time.min)
    punches = defaultdict(list)
    for p in db.scalars(select(AttendancePunch).where(AttendancePunch.employee_id == employee.id,
                                                      AttendancePunch.punched_at >= lo, AttendancePunch.punched_at < hi)
                        .order_by(AttendancePunch.punched_at)):
        punches[p.punched_at.date()].append(p)
    marks = {a.day: a for a in db.scalars(select(AttendanceDay).where(
        AttendanceDay.employee_id == employee.id, AttendanceDay.day.between(start, end)))}
    holidays = {h.day: h.name for h in db.scalars(select(PublicHoliday).where(PublicHoliday.day.between(start, end)))}
    leaves = {}
    for lv in db.scalars(select(Leave).where(Leave.employee_id == employee.id, Leave.deleted_at.is_(None),
                                             Leave.status == "approved", Leave.start_date <= end,
                                             Leave.end_date >= start)):
        x = max(lv.start_date, start)
        while x <= min(lv.end_date, end):
            leaves[x] = lv.kind
            x += timedelta(days=1)
    jobs = defaultdict(list)
    if employee.user_id:
        for j in db.scalars(select(FieldJob).where(
                FieldJob.technician_id == employee.user_id, FieldJob.deleted_at.is_(None),
                FieldJob.status != "cancelled",
                FieldJob.scheduled_at >= lo - timedelta(days=1), FieldJob.scheduled_at < hi + timedelta(days=1))):
            jobs[local_date(j.scheduled_at)].append(j)
    zones = db.scalars(select(WorkZone).where(WorkZone.is_active.is_(True))).all()

    day_pay, hour_pay = rates(rules, employee.base_salary)
    days, unnotified = [], 0
    tot = defaultdict(Decimal)
    x = start
    while x <= end:
        mark = marks.get(x)
        ps = punches.get(x, [])
        info = {"day": x.isoformat(), "kind": "normal", "first": None, "last": None, "punches": len(ps),
                "late": 0, "overtime": 0, "deduct_days": "0", "deduct_minutes": 0, "extra": "0", "flags": []}
        # the day's kind
        kind, zone = "normal", None
        if x.weekday() in rules.weekly_off or x in holidays:
            kind = "off"
        if jobs.get(x):
            j = jobs[x][0]
            if j.latitude is not None and j.longitude is not None:
                zone = zone_of(zones, j.latitude, j.longitude)
                kind = "install" if zone is not None else "travel"
            else:
                kind = "install"
                info["flags"].append("مكان المهمة مش متحدد")
            info["job"] = str(j.id)
        if x in leaves:
            kind = "leave"
        if mark and mark.kind:
            kind = mark.kind
        info["kind"] = kind
        excuse = mark.excuse if mark else "none"
        # the day's times
        first = last = None
        if ps:
            sources = {p.source for p in ps if p.punched_at.hour < 13}
            morning = ps
            if len(sources) > 1:
                pick = mark.start_source if mark and mark.start_source else None
                if pick:
                    morning = [p for p in ps if p.source == pick] or ps
                else:
                    info["flags"].append("بصمتين الصبح (الجهاز والموبايل): محتاج اعتماد")
            first = morning[0].punched_at
            last = ps[-1].punched_at if len(ps) > 1 else None
        if mark and mark.manual_in:
            first = datetime.combine(x, mark.manual_in)
        if mark and mark.manual_out:
            last = datetime.combine(x, mark.manual_out)
        if first and last and last <= first:
            last = None
        info["first"] = first.isoformat() if first else None
        info["last"] = last.isoformat() if last else None
        counted = track_from is not None and track_from <= x and (x < today or first is not None)
        if not counted or (employee.hire_date and x < employee.hire_date) or (employee.end_date and x > employee.end_date):
            info["kind"] = "not_counted"
            days.append(info)
            x += timedelta(days=1)
            continue

        if first is not None:
            tot["present"] += 1
            if last is None:
                info["flags"].append("بصمة واحدة بس")
            res = day_result(rules, x, "normal" if kind == "leave" else kind, first, last, excuse,
                             mark.permission_minutes if mark else 0)
            info["late"], info["overtime"] = res["late"], res["overtime"]
            info["deduct_minutes"] = res["late_cut"]
            info["deduct_days"] = str(res["late_day"])
            tot["late"] += res["late"]
            tot["late_minutes_cut"] += res["late_cut"]
            tot["late_days"] += res["late_day"]
            tot["overtime"] += res["overtime"]
            extra = Decimal(0)
            if kind == "off":
                extra += rules.holiday_day_value * day_pay
            elif kind == "travel":
                off_day = x.weekday() in rules.weekly_off or x in holidays   # a day off: the whole value
                value = max(rules.travel_day_value, rules.holiday_day_value) if off_day else rules.travel_day_value - 1
                extra += value * day_pay + rules.travel_meal
                tot["travel"] += 1
            elif kind == "install" and rules.install_transport_by_zone and zone is not None:
                extra += zone.transport_allowance
            info["extra"] = str(money(extra))
            tot["extra"] += extra
        elif kind in ("normal", "install", "travel"):
            # absent on a working day
            if excuse == "excused":
                info["kind"] = "excused"
            else:
                tot["absent"] += 1
                if kind in ("install", "travel") and rules.absence_install_day_days is not None:
                    cost = rules.absence_install_day_days
                elif excuse == "notified":
                    cost = rules.absence_notified_days
                else:
                    unnotified += 1
                    cost = rules.absence_unnotified_days
                    if rules.absence_repeat_doubles:
                        cost = cost * (2 ** (unnotified - 1))
                info["kind"] = "absent"
                info["deduct_days"] = str(cost)
                tot["absence_days"] += cost
        if info["flags"]:
            tot["review"] += 1
        days.append(info)
        x += timedelta(days=1)

    deduction = (tot["absence_days"] + tot["late_days"]) * day_pay + Decimal(tot["late_minutes_cut"]) / 60 * hour_pay
    overtime_amount = Decimal(tot["overtime"]) / 60 * hour_pay * rules.overtime_multiplier if rules.overtime_enabled else 0
    return {
        "days": days,
        "present_days": Decimal(tot["present"]),
        "absent_days": Decimal(tot["absent"]),
        "late_minutes": int(tot["late"]),
        "attendance_deduction": money(deduction),
        "overtime_minutes": int(tot["overtime"]) if rules.overtime_enabled else 0,
        "overtime_amount": money(overtime_amount),
        "allowances": money(tot["extra"]),
        "travel_days": int(tot["travel"]),
        "review_days": int(tot["review"]),
        "day_pay": money(day_pay),
        "hour_pay": money(hour_pay),
    }


# ------------------------------------------------------------------ sales commission
def collections(db, employee_id, start: date, end: date) -> Decimal:
    """Money that came in during the month for the sales of this salesperson (work orders, or invoices not tied to
    a work order). Cancelled receipts and their reversals are left out."""
    from app.modules.invoicing.models import Invoice
    from app.modules.production.models import WorkOrder
    from app.modules.treasury.models import CashTransaction as T
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TZ)
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    wo = select(WorkOrder.id).where(WorkOrder.salesperson_id == employee_id)
    inv = select(Invoice.id).where(Invoice.salesperson_id == employee_id)
    total = db.scalar(select(func.coalesce(func.sum(T.amount), 0)).where(
        T.direction == "in", T.reversed.is_(False), T.reverses_id.is_(None), T.at >= lo, T.at < hi,
        or_(T.work_order_id.in_(wo), and_(T.work_order_id.is_(None), T.invoice_id.in_(inv)))))
    return money(total or 0)


def commission(rules: Rules, collected: Decimal, forced: bool) -> Decimal:
    if rules.commission_rate <= 0:
        return Decimal(0)
    if collected < rules.commission_min_collections and not forced:
        return Decimal(0)
    return money(collected * rules.commission_rate)
