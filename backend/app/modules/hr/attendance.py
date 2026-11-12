"""الحضور والانصراف: punches come straight from the fingerprint device (ZKTeco «ADMS» / push, e.g. uFace402 Plus).

The device is told, once, the server's address and port (Menu → Comm → Cloud Server Setting). From then on it
calls the server by itself over the factory network:

    GET  /iclock/cdata?SN=<serial>&options=all   → the server answers how to send (and from which stamp)
    POST /iclock/cdata?SN=<serial>&table=ATTLOG  → the punches, one per line: PIN \t time \t state \t verify ...
    GET  /iclock/getrequest?SN=<serial>          → every few seconds: "anything for me?" (always "OK": nothing)

A punch is kept only from a device an HR user registered (its serial number, on the device's sticker or in
Menu → System Info → Device Info); the serial tells the server which company it belongs to. The device keeps its
punches while the network or the server is down and sends them later; the same punch sent twice is kept once.
The device's own names, faces and fingerprints are never read: a punch is matched to an employee by the number
the employee has on the device («رقم البصمة» on the employee's file).
"""
from __future__ import annotations

import logging
import re
import socket
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, true, update
from sqlalchemy.dialects.postgresql import insert

from app.api.common import ORMModel, Page, PageParams, Record, VersionedUpdate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.config import get_settings
from app.core.errors import Conflict, ValidationFailed
from app.core.pii import log_pii
from app.db.base import utcnow
from app.db.session import system_session, tenant_session
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.hr.models import AttendanceDevice, AttendancePunch, Employee
from app.modules.org.models import Branch
from app.tenancy.context import require

log = logging.getLogger("mytech.attendance")

SERIAL = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
PIN = re.compile(r"^[0-9A-Za-z]{1,20}$")
MAX_BODY = 4 * 1024 * 1024


# ================================================================ what the device calls (no account: its serial)
device_router = APIRouter(include_in_schema=False)


def _text(body: str = "OK") -> PlainTextResponse:
    return PlainTextResponse(body)


def _device(serial: str) -> AttendanceDevice | None:
    if not SERIAL.match(serial or ""):
        return None
    with system_session() as sdb:                 # the device names no company: find it by its serial
        dev = sdb.scalar(select(AttendanceDevice).where(AttendanceDevice.serial == serial))
        if dev is not None:
            sdb.expunge(dev)
        return dev


def _seen(dev: AttendanceDevice, **values) -> None:
    db = tenant_session(dev.company_id)
    try:
        db.execute(update(AttendanceDevice).where(AttendanceDevice.id == dev.id)
                   .values(last_seen_at=utcnow(), **values).execution_options(synchronize_session=False))
        db.commit()
    finally:
        db.close()


def parse_attlog(body: str) -> list[dict]:
    """The device's ATTLOG lines → [{pin, punched_at, state, verify}]; lines that cannot be read are skipped."""
    out = []
    for line in body.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:                        # some firmwares use spaces: PIN date time state verify
            bits = line.split()
            parts = [bits[0], " ".join(bits[1:3]), *bits[3:]] if len(bits) >= 3 else []
        if len(parts) < 2 or not PIN.match(parts[0].strip()):
            continue
        try:
            at = datetime.strptime(parts[1].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        def num(i: int) -> int:
            try:
                return int(parts[i]) if len(parts) > i and parts[i].strip() else 0
            except ValueError:
                return 0
        out.append({"pin": parts[0].strip(), "punched_at": at, "state": num(2), "verify": num(3)})
    return out


def store_punches(dev: AttendanceDevice, punches: list[dict], stamp: str | None) -> int:
    """Keep the punches of one device (each once); returns how many were new."""
    db = tenant_session(dev.company_id)
    try:
        pins = {p["pin"] for p in punches}
        who = dict(db.execute(select(Employee.attendance_pin, Employee.id).where(
            Employee.attendance_pin.in_(pins), Employee.deleted_at.is_(None))).all()) if pins else {}
        new = 0
        for i in range(0, len(punches), 500):
            rows = [{"id": uuid.uuid4(), "company_id": dev.company_id, "device_serial": dev.serial,
                     "employee_id": who.get(p["pin"]), "version": 1, **p} for p in punches[i:i + 500]]
            res = db.execute(insert(AttendancePunch).values(rows).on_conflict_do_nothing(
                index_elements=["company_id", "device_serial", "pin", "punched_at"]).returning(AttendancePunch.id))
            new += len(res.all())
        # a morning punch on the device when the app has one too (or the other way): the manager picks one
        from types import SimpleNamespace

        from app.modules.hr.payrules import warn_two_starts
        for emp_id, day in {(who[p["pin"]], p["punched_at"].date()) for p in punches
                            if p["pin"] in who and p["punched_at"].hour < 13}:
            emp = db.get(Employee, emp_id)
            warn_two_starts(db, SimpleNamespace(user_id=None), emp, day)
        values = {"last_seen_at": utcnow()}
        if punches:
            newest = max(p["punched_at"] for p in punches)
            if dev.last_punch_at is None or newest > dev.last_punch_at:
                values["last_punch_at"] = newest
        if stamp:
            values["attlog_stamp"] = stamp[:40]
        db.execute(update(AttendanceDevice).where(AttendanceDevice.id == dev.id).values(**values)
                   .execution_options(synchronize_session=False))
        db.commit()
        return new
    finally:
        db.close()


def _options(dev: AttendanceDevice) -> str:
    return "\n".join([
        f"GET OPTION FROM: {dev.serial}",
        f"ATTLOGStamp={dev.attlog_stamp or 'None'}",   # None the first time: send every punch it holds
        "OPERLOGStamp=9999",                           # nothing about the device's users / admins
        "ATTPHOTOStamp=None",
        "ErrorDelay=30",
        "Delay=10",
        "TransTimes=00:00;14:05",
        "TransInterval=1",
        "TransFlag=TransData AttLog",
        "Realtime=1",
        "Encrypt=None",
    ]) + "\n"


@device_router.get("/iclock/cdata")
@device_router.get("/iclock/cdata.aspx")
async def device_hello(request: Request):
    serial = request.query_params.get("SN", "")
    dev = await run_in_threadpool(_device, serial)
    if dev is None:
        log.info("fingerprint device not registered: %s", serial[:40])
        return _text()
    info = " ".join(f"{k}={request.query_params[k]}" for k in ("pushver", "language") if k in request.query_params)
    await run_in_threadpool(_seen, dev, **({"info": info[:200]} if info else {}))
    return _text(_options(dev) if dev.is_active else "OK")


@device_router.post("/iclock/cdata")
@device_router.post("/iclock/cdata.aspx")
async def device_upload(request: Request):
    q = request.query_params
    dev = await run_in_threadpool(_device, q.get("SN", ""))
    body = await request.body()
    if dev is None or not dev.is_active:
        return _text()
    if len(body) > MAX_BODY:
        return PlainTextResponse("ERROR: too large", status_code=413)
    if q.get("table", "").upper() != "ATTLOG":     # users, operations, photos: not kept
        await run_in_threadpool(_seen, dev)
        return _text()
    punches = parse_attlog(body.decode("utf-8", errors="replace"))
    new = await run_in_threadpool(store_punches, dev, punches, q.get("Stamp"))
    log.info("fingerprint device %s sent %d punches (%d new)", dev.serial, len(punches), new)
    return _text(f"OK: {len(punches)}")


@device_router.get("/iclock/getrequest")
@device_router.get("/iclock/getrequest.aspx")
async def device_poll(request: Request):
    dev = await run_in_threadpool(_device, request.query_params.get("SN", ""))
    if dev is not None:
        await run_in_threadpool(_seen, dev)
    return _text()


@device_router.post("/iclock/devicecmd")
@device_router.post("/iclock/devicecmd.aspx")
async def device_cmd_result():
    return _text()


# ================================================================ HR screens
router = APIRouter(prefix="/attendance", tags=["attendance"])


class FingerprintDeviceIn(BaseModel):
    serial: str = Field(pattern=SERIAL.pattern)
    name: str = Field("", max_length=120)
    branch_id: uuid.UUID | None = None


class FingerprintDeviceUpdate(VersionedUpdate):
    name: str | None = Field(None, max_length=120)
    branch_id: uuid.UUID | None = None
    is_active: bool | None = None


class FingerprintDeviceOut(Record):
    serial: str
    name: str
    branch_id: uuid.UUID | None
    is_active: bool
    last_seen_at: datetime | None
    last_punch_at: datetime | None
    info: str
    punches: int = 0
    online: bool = False


class FingerprintDevicesOut(BaseModel):
    devices: list[FingerprintDeviceOut]
    server_addresses: list[str]
    server_port: int
    server_domain: bool = False      # the address is a domain name (the cloud server): «Enable Domain Name» ON
    server_https: bool = False


def server_addresses() -> list[str]:
    """This PC's addresses on the factory network (what the device is told to call)."""
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))           # no packet is sent: only the route is looked up
        found.insert(0, s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return list(dict.fromkeys(a for a in found if not a.startswith("127.")))


def _device_out(db, dev: AttendanceDevice) -> FingerprintDeviceOut:
    out = FingerprintDeviceOut.model_validate(dev)
    out.punches = db.scalar(select(func.count()).select_from(AttendancePunch)
                            .where(AttendancePunch.device_serial == dev.serial)) or 0
    out.online = bool(dev.last_seen_at and utcnow() - dev.last_seen_at < timedelta(minutes=3))
    return out


@router.get("/devices", response_model=FingerprintDevicesOut)
def list_devices(dc=Depends(require("hr.read"))):
    db, _ = dc
    devs = db.scalars(select(AttendanceDevice).order_by(AttendanceDevice.created_at)).all()
    devices = [_device_out(db, d) for d in devs]
    public = get_settings().public_url.strip()
    if public:                                     # the cloud server: the device calls its public address
        from urllib.parse import urlsplit
        u = urlsplit(public if "://" in public else "http://" + public)
        https = u.scheme == "https"
        host = u.hostname or ""
        return FingerprintDevicesOut(devices=devices, server_addresses=[host], server_port=u.port or (443 if https else 80),
                                     server_domain=not re.fullmatch(r"[\d.]+", host), server_https=https)
    return FingerprintDevicesOut(devices=devices, server_addresses=server_addresses(),
                                 server_port=get_settings().http_port)


@router.post("/devices", response_model=FingerprintDeviceOut, status_code=201)
def add_device(body: FingerprintDeviceIn, dc=Depends(require("hr.write"))):
    db, ctx = dc
    if body.branch_id:
        get_or_404(db, Branch, body.branch_id)
    with system_session() as sdb:                  # a serial is one company's on the whole server
        taken = sdb.scalar(select(AttendanceDevice.company_id).where(AttendanceDevice.serial == body.serial))
    if taken is not None:
        raise Conflict("This device is already added", code="DEVICE_TAKEN")
    dev = AttendanceDevice(serial=body.serial, name=body.name or body.serial, branch_id=body.branch_id,
                           is_active=True, info="")
    db.add(dev)
    db.flush()
    audit(db, dev, "create")
    db.commit()
    return _device_out(db, dev)


@router.patch("/devices/{device_id}", response_model=FingerprintDeviceOut)
def update_device(device_id: uuid.UUID, body: FingerprintDeviceUpdate, dc=Depends(require("hr.write"))):
    db, ctx = dc
    dev = get_or_404(db, AttendanceDevice, device_id)
    check_version(dev, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("branch_id"):
        get_or_404(db, Branch, data["branch_id"])
    before = snapshot(dev)
    apply_changes(dev, data)
    audit(db, dev, "update", before)
    db.commit()
    return _device_out(db, dev)


class PunchOut(ORMModel):
    id: uuid.UUID
    punched_at: datetime
    pin: str
    employee_id: uuid.UUID | None
    employee_name: str | None = None
    device_serial: str
    state: int
    verify: int


class DayOut(BaseModel):
    """One employee's day: first and last punch."""
    day: date
    employee_id: uuid.UUID | None
    employee_name: str | None
    pin: str
    first: datetime
    last: datetime
    punches: int


class UnlinkedOut(BaseModel):
    pin: str
    punches: int
    last: datetime


def _range(date_from: date | None, date_to: date | None):
    date_to = date_to or date.today()
    date_from = date_from or date_to
    if date_from > date_to:
        raise ValidationFailed("date_from is after date_to", code="BAD_RANGE")
    if (date_to - date_from).days > 62:
        raise ValidationFailed("Up to two months at a time", code="RANGE_TOO_LONG")
    return datetime.combine(date_from, datetime.min.time()), datetime.combine(date_to + timedelta(days=1),
                                                                              datetime.min.time())


def _punches_stmt(ctx, start, end, employee_id):
    stmt = (select(AttendancePunch, Employee.full_name)
            .outerjoin(Employee, Employee.id == AttendancePunch.employee_id)
            .where(AttendancePunch.punched_at >= start, AttendancePunch.punched_at < end))
    branches = ctx.branches_for("hr.read")
    if branches is not None:                        # a branch's HR sees its own employees only
        stmt = stmt.where(Employee.branch_id.in_(branches))
    if employee_id:
        stmt = stmt.where(AttendancePunch.employee_id == employee_id)
    return stmt


@router.get("/punches", response_model=Page[PunchOut])
def list_punches(date_from: date | None = None, date_to: date | None = None, employee_id: uuid.UUID | None = None,
                 params: PageParams = Depends(), dc=Depends(require("hr.read"))):
    db, ctx = dc
    start, end = _range(date_from, date_to)
    stmt = _punches_stmt(ctx, start, end, employee_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(AttendancePunch.punched_at.desc())
                      .limit(params.limit).offset(params.offset)).all()
    items = []
    for p, name in rows:
        out = PunchOut.model_validate(p)
        out.employee_name = name
        items.append(out)
    log_pii(db, ctx, "employee", {p.employee_id for p, _ in rows if p.employee_id}, "list", ["full_name"])
    db.commit()
    return {"items": items, "total": total, "limit": params.limit, "offset": params.offset}


@router.get("/days", response_model=list[DayOut])
def attendance_days(date_from: date | None = None, date_to: date | None = None,
                    employee_id: uuid.UUID | None = None, dc=Depends(require("hr.read"))):
    """Each employee's first and last punch per day (a night shift past midnight shows as two days)."""
    db, ctx = dc
    start, end = _range(date_from, date_to)
    days: dict[tuple, DayOut] = {}
    for p, name in db.execute(_punches_stmt(ctx, start, end, employee_id).order_by(AttendancePunch.punched_at)):
        key = (p.punched_at.date(), p.employee_id or p.pin)
        d = days.get(key)
        if d is None:
            days[key] = DayOut(day=p.punched_at.date(), employee_id=p.employee_id, employee_name=name, pin=p.pin,
                               first=p.punched_at, last=p.punched_at, punches=1)
        else:
            d.last, d.punches = p.punched_at, d.punches + 1
    out = sorted(days.values(), key=lambda d: (d.day, d.employee_name or "", d.pin), reverse=False)
    log_pii(db, ctx, "employee", {d.employee_id for d in out if d.employee_id}, "list", ["full_name"])
    db.commit()
    return out


@router.get("/unlinked", response_model=list[UnlinkedOut])
def unlinked_pins(dc=Depends(require("hr.read"))):
    """Numbers on the device no employee has yet: give them to the employees (their file → رقم البصمة)."""
    db, _ = dc
    rows = db.execute(select(AttendancePunch.pin, func.count(), func.max(AttendancePunch.punched_at))
                      .where(AttendancePunch.employee_id.is_(None)).group_by(AttendancePunch.pin)
                      .order_by(AttendancePunch.pin)).all()
    return [UnlinkedOut(pin=pin, punches=n, last=last) for pin, n, last in rows]


def link_pin(db, employee: Employee) -> None:
    """After an employee gets (or changes) a number: earlier punches with that number become theirs."""
    if employee.attendance_pin:
        db.execute(update(AttendancePunch).where(AttendancePunch.pin == employee.attendance_pin,
                                                 AttendancePunch.employee_id.is_(None))
                   .values(employee_id=employee.id).execution_options(synchronize_session=False))


def check_pin(db, pin: str | None, employee_id=None) -> None:
    if not pin:
        return
    if not PIN.match(pin):
        raise ValidationFailed("The fingerprint number is digits / letters only", code="BAD_PIN")
    other = db.scalar(select(Employee.id).where(Employee.attendance_pin == pin, Employee.deleted_at.is_(None),
                                                Employee.id != employee_id if employee_id else true()))
    if other is not None:
        raise Conflict("Another employee has this fingerprint number", code="PIN_TAKEN")
