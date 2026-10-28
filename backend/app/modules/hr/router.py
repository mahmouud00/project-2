"""الموارد البشرية: الموظفين، الحوافز والخصومات والسلف، الإجازات، وكشوف المرتبات.

Money leaves the treasury twice: an advance (سلفة) when it is given, and the net salary when a payroll run is paid
(one cash payment per employee, party "employee"). A paid run is frozen. Names, phones, national IDs and addresses
are personal data: every read is logged.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.modules.deletions.router import deletable
from app.api.common import DeleteResult, ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, ValidationFailed
from app.core.numbering import next_number
from app.core.pii import log_pii
from app.db.base import utcnow
from app.modules.crm.router import branch_scope, get_or_404
from app.modules.hr.models import DEPARTMENTS, Employee, EmployeeEntry, Leave, PayrollRun, Payslip
from app.modules.org.models import Branch, User
from app.tenancy.context import require

router = APIRouter(tags=["hr"])

EMPLOYEE_PII = list(Employee.__pii__)
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
DEPT = "^(" + "|".join(DEPARTMENTS) + ")$"
CENT = Decimal("0.01")


def _money(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


# ---------------------------------------------------------------- employees
class EmployeeIn(BaseModel):
    code: str | None = Field(None, max_length=40)
    full_name: str = Field(min_length=1, max_length=200)
    job_title: str = ""
    department: str = Field("other", pattern=DEPT)
    branch_id: uuid.UUID
    user_id: uuid.UUID | None = None
    phone: str | None = None
    national_id: str | None = Field(None, max_length=20)
    address: str | None = None
    hire_date: date | None = None
    base_salary: Decimal = Field(Decimal(0), ge=0)
    annual_leave_days: Decimal = Field(Decimal(21), ge=0)
    notes: str = ""


class EmployeeUpdate(VersionedUpdate):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    job_title: str | None = None
    department: str | None = Field(None, pattern=DEPT)
    branch_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    phone: str | None = None
    national_id: str | None = Field(None, max_length=20)
    address: str | None = None
    hire_date: date | None = None
    end_date: date | None = None
    status: str | None = Field(None, pattern="^(active|left)$")
    base_salary: Decimal | None = Field(None, ge=0)
    annual_leave_days: Decimal | None = Field(None, ge=0)
    notes: str | None = None


class EmployeeOut(Record):
    code: str
    full_name: str
    job_title: str
    department: str
    branch_id: uuid.UUID
    user_id: uuid.UUID | None
    phone: str | None
    national_id: str | None
    address: str | None
    hire_date: date | None
    end_date: date | None
    status: str
    base_salary: Decimal
    annual_leave_days: Decimal
    notes: str


class EmployeeBrief(ORMModel):
    """For pickers (e.g. the salesperson of a sale): no personal data beyond the name."""
    id: uuid.UUID
    code: str
    full_name: str
    department: str
    job_title: str
    branch_id: uuid.UUID
    user_id: uuid.UUID | None
    status: str


def _employee(db, ctx, eid, permission="hr.read") -> Employee:
    e = get_or_404(db, Employee, eid)
    ctx.require(permission, e.branch_id)
    return e


def _check_user(db, user_id):
    if user_id is not None:
        get_or_404(db, User, user_id)
        if db.scalar(select(Employee.id).where(Employee.user_id == user_id, Employee.deleted_at.is_(None))):
            raise Conflict("This user is already linked to an employee", code="USER_LINKED")


@router.get("/employees", response_model=Page[EmployeeOut])
def list_employees(department: str | None = None, status: str | None = None, branch_id: uuid.UUID | None = None,
                   q: str | None = None, params: PageParams = Depends(), dc=Depends(require("hr.read"))):
    db, ctx = dc
    stmt = select(Employee).where(Employee.deleted_at.is_(None)).order_by(Employee.full_name)
    stmt = branch_scope(stmt, ctx, "hr.read", Employee.branch_id)
    if department:
        stmt = stmt.where(Employee.department == department)
    if status:
        stmt = stmt.where(Employee.status == status)
    if branch_id:
        stmt = stmt.where(Employee.branch_id == branch_id)
    if q:
        stmt = stmt.where(or_(Employee.full_name.ilike(f"%{q}%"), Employee.code.ilike(f"%{q}%"),
                              Employee.job_title.ilike(f"%{q}%")))
    page = paginate(db, stmt, params, EmployeeOut)
    log_pii(db, ctx, "employee", [e.id for e in page["items"]], "list", ["full_name", "phone"])
    db.commit()
    return page


@router.get("/employees/brief", response_model=list[EmployeeBrief])
def employee_names(department: str | None = None, dc=Depends(require("quotes.read"))):
    """Employees' names for choosing the salesperson of a sale and showing it (whoever can see quotations).
    Those who left are listed too (old sales still show their name); pick only active ones."""
    db, ctx = dc
    stmt = select(Employee).where(Employee.deleted_at.is_(None)).order_by(Employee.full_name)
    if department:
        stmt = stmt.where(Employee.department == department)
    rows = db.scalars(stmt).all()
    log_pii(db, ctx, "employee", [e.id for e in rows], "list", ["full_name"])
    db.commit()
    return rows


@router.post("/employees", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeIn, dc=Depends(require("hr.create"))):
    db, ctx = dc
    ctx.require("hr.create", body.branch_id)
    get_or_404(db, Branch, body.branch_id)
    _check_user(db, body.user_id)
    data = body.model_dump()
    data["code"] = data["code"] or next_number(db, "employee", "EM")
    if db.scalar(select(Employee).where(Employee.code == data["code"])):
        raise Conflict("Employee code exists", code="DUPLICATE_CODE")
    e = Employee(**data)
    db.add(e)
    db.flush()
    audit(db, e, "create")
    log_pii(db, ctx, "employee", [e.id], "create", [k for k in EMPLOYEE_PII if data.get(k)])
    db.commit()
    return e


@router.get("/employees/{eid}", response_model=EmployeeOut)
def get_employee(eid: uuid.UUID, dc=Depends(require("hr.read"))):
    db, ctx = dc
    e = _employee(db, ctx, eid)
    log_pii(db, ctx, "employee", [e.id], "view", EMPLOYEE_PII)
    db.commit()
    return e


@router.patch("/employees/{eid}", response_model=EmployeeOut)
def update_employee(eid: uuid.UUID, body: EmployeeUpdate, dc=Depends(require("hr.write"))):
    db, ctx = dc
    e = _employee(db, ctx, eid, "hr.write")
    check_version(e, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("branch_id"):
        ctx.require("hr.write", data["branch_id"])
        get_or_404(db, Branch, data["branch_id"])
    if "user_id" in data and data["user_id"] != e.user_id:
        _check_user(db, data["user_id"])
    if data.get("status") == "left" and not data.get("end_date") and not e.end_date:
        data["end_date"] = date.today()
    before = snapshot(e)
    apply_changes(e, data)
    audit(db, e, "update", before)
    log_pii(db, ctx, "employee", [e.id], "update", [k for k in data if k in EMPLOYEE_PII])
    db.commit()
    return e


def _employee_in_use(sdb, employee_id) -> list:
    """Quotations not accepted yet sold by this employee: another salesperson is chosen."""
    from app.modules.deletions.router import OpenWork
    from app.modules.sales.models import Quotation

    return [OpenWork(q.company_id, q.branch_id, q.created_by, "notify.sales", "sales", f"عرض السعر {q.number}",
                     f"quotations/{q.id}")
            for q in sdb.scalars(select(Quotation).where(Quotation.salesperson_id == employee_id,
                                                         Quotation.deleted_at.is_(None),
                                                         Quotation.status.in_(("draft", "sent"))))]


@deletable(router, "/employees/{eid}", "employees", ("الموظف", Employee, "code"), open_work=_employee_in_use)
def delete_employee(eid: uuid.UUID, dc=Depends(require("hr.delete"))):
    """Deleted (hidden from every list). With salaries, advances or sales they are also marked as left, and that
    history keeps showing them."""
    from app.modules.invoicing.models import Invoice
    from app.modules.production.models import WorkOrder
    from app.modules.sales.models import Quotation

    db, ctx = dc
    e = _employee(db, ctx, eid, "hr.delete")
    before = snapshot(e)
    used = any(db.scalar(select(m.id).where(col == e.id).limit(1)) for m, col in (
        (Payslip, Payslip.employee_id), (EmployeeEntry, EmployeeEntry.employee_id),
        (Quotation, Quotation.salesperson_id), (WorkOrder, WorkOrder.salesperson_id),
        (Invoice, Invoice.salesperson_id)))
    if used:
        e.status = "left"
        e.end_date = e.end_date or date.today()
    e.deleted_at = utcnow()
    audit(db, e, "delete", before)
    log_pii(db, ctx, "employee", [e.id], "delete", ["full_name"])
    db.commit()
    return DeleteResult(result="deleted")


@router.get("/employees/{eid}/summary")
def employee_summary(eid: uuid.UUID, year: int | None = None, dc=Depends(require("hr.read"))):
    """Leave taken this year and what is left of the annual leave, and advances still owed."""
    db, ctx = dc
    e = _employee(db, ctx, eid)
    year = year or date.today().year
    leaves = db.scalars(select(Leave).where(Leave.employee_id == e.id, Leave.deleted_at.is_(None),
                                            Leave.status == "approved")).all()
    by_kind: dict[str, Decimal] = {}
    for lv in leaves:
        if lv.start_date.year == year:
            by_kind[lv.kind] = by_kind.get(lv.kind, Decimal(0)) + lv.days
    advances = db.scalars(select(EmployeeEntry).where(EmployeeEntry.employee_id == e.id,
                                                      EmployeeEntry.kind == "advance",
                                                      EmployeeEntry.deleted_at.is_(None))).all()
    owed = sum((a.amount - a.repaid for a in advances), Decimal(0))
    return {"year": year, "leave_days": {k: str(v) for k, v in by_kind.items()},
            "annual_leave_left": str(e.annual_leave_days - by_kind.get("annual", Decimal(0))),
            "advances_owed": str(owed)}


@router.get("/employees/{eid}/sales")
def employee_sales(eid: uuid.UUID, year: int | None = None, dc=Depends(require("hr.read"))):
    """المبيعات بتاعة الموظف: his quotations, work orders and invoices (a salesperson's profile)."""
    from app.modules.crm.models import Customer
    from app.modules.invoicing.models import Invoice
    from app.modules.production.models import WorkOrder
    from app.modules.sales.models import Quotation

    db, ctx = dc
    e = _employee(db, ctx, eid)
    year = year or date.today().year
    start, end = date(year, 1, 1), date(year, 12, 31)

    def in_year(col):
        return func.date(col).between(start, end)

    quotes = db.scalars(select(Quotation).where(Quotation.salesperson_id == e.id, Quotation.deleted_at.is_(None),
                                                in_year(Quotation.created_at))
                        .order_by(Quotation.created_at.desc())).all()
    orders = db.scalars(select(WorkOrder).where(WorkOrder.salesperson_id == e.id, WorkOrder.deleted_at.is_(None),
                                                WorkOrder.stage != "cancelled", in_year(WorkOrder.created_at))
                        .order_by(WorkOrder.created_at.desc())).all()
    invoices = db.scalars(select(Invoice).where(Invoice.salesperson_id == e.id, Invoice.deleted_at.is_(None),
                                                Invoice.status == "issued", Invoice.issue_date.between(start, end))
                          .order_by(Invoice.issue_date.desc())).all()
    names = {c.id: c.name for c in db.scalars(select(Customer).where(Customer.id.in_(
        {x.customer_id for x in [*quotes, *orders, *invoices]})))} if (quotes or orders or invoices) else {}
    log_pii(db, ctx, "customer", list(names), "list", ["name"])
    db.commit()
    accepted = [q for q in quotes if q.status == "accepted"]
    return {
        "year": year,
        "quotations": {"count": len(quotes), "accepted": len(accepted),
                       "accepted_total": str(sum((q.total for q in accepted), Decimal(0)))},
        "work_orders": {"count": len(orders), "total": str(sum((o.total for o in orders), Decimal(0))),
                        "paid": str(sum((o.paid_amount for o in orders), Decimal(0)))},
        "invoices": {"count": len(invoices), "total": str(sum((i.total for i in invoices), Decimal(0)))},
        "orders": [{"id": str(o.id), "number": o.number, "customer": names.get(o.customer_id, ""), "stage": o.stage,
                    "total": str(o.total), "paid": str(o.paid_amount), "date": o.created_at.date().isoformat()}
                   for o in orders[:100]],
        "quotes": [{"id": str(q.id), "number": q.number, "customer": names.get(q.customer_id, ""), "status": q.status,
                    "total": str(q.total), "date": q.created_at.date().isoformat()} for q in quotes[:100]],
    }


# ---------------------------------------------------------------- bonuses, deductions, advances
class EntryIn(BaseModel):
    employee_id: uuid.UUID
    kind: str = Field(pattern="^(bonus|deduction|advance)$")
    amount: Decimal = Field(gt=0)
    entry_date: date | None = None
    month: str | None = Field(None, pattern=MONTH)   # default: the month of entry_date
    installment: Decimal | None = Field(None, gt=0)   # advance: taken back per month (default: all at once)
    cashbox_id: uuid.UUID | None = None               # advance: paid from this cashbox
    note: str = ""


class EntryOut(Record):
    employee_id: uuid.UUID
    kind: str
    entry_date: date
    month: str
    amount: Decimal
    installment: Decimal | None
    repaid: Decimal
    cash_transaction_id: uuid.UUID | None
    payslip_id: uuid.UUID | None
    note: str


@router.get("/employees/{eid}/entries", response_model=list[EntryOut])
def list_entries(eid: uuid.UUID, dc=Depends(require("hr.read"))):
    db, ctx = dc
    e = _employee(db, ctx, eid)
    return db.scalars(select(EmployeeEntry).where(EmployeeEntry.employee_id == e.id,
                                                  EmployeeEntry.deleted_at.is_(None))
                      .order_by(EmployeeEntry.entry_date.desc(), EmployeeEntry.created_at.desc())).all()


@router.post("/employee-entries", response_model=EntryOut, status_code=201)
def create_entry(body: EntryIn, dc=Depends(require("hr.create"))):
    db, ctx = dc
    e = _employee(db, ctx, body.employee_id, "hr.create")
    when = body.entry_date or date.today()
    entry = EmployeeEntry(employee_id=e.id, kind=body.kind, entry_date=when, month=body.month or when.strftime("%Y-%m"),
                          amount=_money(body.amount), note=body.note)
    if body.kind == "advance":
        from app.modules.treasury.models import Cashbox
        from app.modules.treasury.router import post_cash

        if body.cashbox_id is None:
            raise ValidationFailed("Choose the cashbox the advance is paid from", code="CASHBOX_REQUIRED")
        box = get_or_404(db, Cashbox, body.cashbox_id)
        ctx.require("treasury.create", box.branch_id)
        entry.installment = _money(min(body.installment or body.amount, body.amount))
        tx = post_cash(db, ctx, box, direction="out", amount=entry.amount, party_type="employee", party_id=e.id,
                       note=f"سلفة {e.code}" + (f" - {body.note}" if body.note else ""))
        entry.cash_transaction_id = tx.id
    db.add(entry)
    db.flush()
    audit(db, entry, "create")
    db.commit()
    return entry


@router.delete("/employee-entries/{entry_id}", response_model=DeleteResult)
def delete_entry(entry_id: uuid.UUID, dc=Depends(require("hr.delete"))):
    """A bonus or deduction not yet paid in a salary. An advance is money: reverse its payment in the treasury."""
    db, ctx = dc
    entry = get_or_404(db, EmployeeEntry, entry_id)
    _employee(db, ctx, entry.employee_id, "hr.delete")
    if entry.kind == "advance":
        raise Conflict("An advance is cancelled by reversing its cash payment", code="ADVANCE_IS_CASH")
    if entry.payslip_id and _paid_slip(db, entry.payslip_id):
        raise Conflict("Already paid in a salary", code="ALREADY_PAID")
    before = snapshot(entry)
    entry.deleted_at = utcnow()
    audit(db, entry, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


def _paid_slip(db, payslip_id) -> bool:
    slip = db.get(Payslip, payslip_id)
    run = db.get(PayrollRun, slip.run_id) if slip else None
    return bool(run and run.status == "paid" and run.deleted_at is None)


def on_cash_reversed(db, tx) -> None:
    """Treasury hook: reversing an advance's payment cancels the advance (only if nothing was taken back yet);
    a salary payment cannot be reversed (the payroll is closed)."""
    if db.scalar(select(Payslip.id).where(Payslip.cash_transaction_id == tx.id)):
        raise Conflict("A paid salary cannot be reversed", code="SALARY_PAID")
    entry = db.scalar(select(EmployeeEntry).where(EmployeeEntry.cash_transaction_id == tx.id))
    if entry:
        if entry.repaid > 0:
            raise Conflict("Part of this advance was already taken from a salary", code="ADVANCE_REPAID")
        before = snapshot(entry)
        entry.deleted_at = utcnow()
        audit(db, entry, "delete", before, note=f"payment {tx.number} reversed")


# ---------------------------------------------------------------- leaves
class LeaveIn(BaseModel):
    employee_id: uuid.UUID
    kind: str = Field(pattern="^(annual|sick|unpaid|other)$")
    start_date: date
    end_date: date
    days: Decimal | None = Field(None, gt=0)   # default: calendar days from start to end
    status: str = Field("approved", pattern="^(requested|approved|rejected)$")
    note: str = ""


class LeaveUpdate(VersionedUpdate):
    status: str | None = Field(None, pattern="^(requested|approved|rejected)$")
    note: str | None = None


class LeaveOut(Record):
    employee_id: uuid.UUID
    kind: str
    start_date: date
    end_date: date
    days: Decimal
    status: str
    note: str


@router.get("/employees/{eid}/leaves", response_model=list[LeaveOut])
def list_leaves(eid: uuid.UUID, dc=Depends(require("hr.read"))):
    db, ctx = dc
    e = _employee(db, ctx, eid)
    return db.scalars(select(Leave).where(Leave.employee_id == e.id, Leave.deleted_at.is_(None))
                      .order_by(Leave.start_date.desc())).all()


@router.post("/employee-leaves", response_model=LeaveOut, status_code=201)
def create_leave(body: LeaveIn, dc=Depends(require("hr.create"))):
    db, ctx = dc
    e = _employee(db, ctx, body.employee_id, "hr.create")
    if body.end_date < body.start_date:
        raise ValidationFailed("The leave ends before it starts", code="BAD_DATES")
    lv = Leave(employee_id=e.id, kind=body.kind, start_date=body.start_date, end_date=body.end_date,
               days=body.days or Decimal((body.end_date - body.start_date).days + 1), status=body.status,
               note=body.note)
    db.add(lv)
    db.flush()
    audit(db, lv, "create")
    db.commit()
    return lv


@router.patch("/employee-leaves/{leave_id}", response_model=LeaveOut)
def update_leave(leave_id: uuid.UUID, body: LeaveUpdate, dc=Depends(require("hr.write"))):
    db, ctx = dc
    lv = get_or_404(db, Leave, leave_id)
    _employee(db, ctx, lv.employee_id, "hr.write")
    check_version(lv, body.version)
    before = snapshot(lv)
    apply_changes(lv, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, lv, "update", before)
    db.commit()
    return lv


@deletable(router, "/employee-leaves/{leave_id}", "employee-leaves", ("إجازة", Leave, "start_date"))
def delete_leave(leave_id: uuid.UUID, dc=Depends(require("hr.delete"))):
    db, ctx = dc
    lv = get_or_404(db, Leave, leave_id)
    _employee(db, ctx, lv.employee_id, "hr.delete")
    before = snapshot(lv)
    lv.deleted_at = utcnow()
    audit(db, lv, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


# ---------------------------------------------------------------- payroll
class RunIn(BaseModel):
    month: str = Field(pattern=MONTH)
    branch_id: uuid.UUID
    notes: str = ""


class PayslipOut(ORMModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    month: str = ""
    employee_code: str = ""
    employee_name: str = ""
    job_title: str = ""
    base_salary: Decimal
    bonuses: Decimal
    deductions: Decimal
    unpaid_leave_days: Decimal
    unpaid_leave_deduction: Decimal
    advance_repayment: Decimal
    gross: Decimal
    net: Decimal
    cash_transaction_id: uuid.UUID | None


class RunOut(Record):
    number: str
    month: str
    branch_id: uuid.UUID
    status: str
    total: Decimal
    cashbox_id: uuid.UUID | None
    paid_at: object | None
    notes: str
    payslips: list[PayslipOut] = []


def _run_out(db, ctx, run: PayrollRun, with_slips: bool = True) -> RunOut:
    out = RunOut.model_validate(run)
    if with_slips:
        rows = db.execute(select(Payslip, Employee).join(Employee, Employee.id == Payslip.employee_id)
                          .where(Payslip.run_id == run.id).order_by(Employee.full_name)).all()
        for slip, emp in rows:
            o = PayslipOut.model_validate(slip)
            o.month, o.employee_code, o.employee_name, o.job_title = run.month, emp.code, emp.full_name, emp.job_title
            out.payslips.append(o)
        log_pii(db, ctx, "employee", [emp.id for _, emp in rows], "view", ["full_name"])
    return out


def _run(db, ctx, run_id, permission) -> PayrollRun:
    run = get_or_404(db, PayrollRun, run_id)
    ctx.require(permission, run.branch_id)
    return run


def _calculate(db, run: PayrollRun) -> None:
    """(Re)build the payslips of a draft run from the employees, their entries, unpaid leave and advances."""
    start, end = _month_bounds(run.month)
    db.query(Payslip).filter(Payslip.run_id == run.id).delete()
    db.flush()
    taken = set(db.scalars(select(Payslip.employee_id).join(PayrollRun, PayrollRun.id == Payslip.run_id).where(
        PayrollRun.month == run.month, PayrollRun.deleted_at.is_(None), PayrollRun.id != run.id)))
    employees = db.scalars(select(Employee).where(
        Employee.branch_id == run.branch_id, Employee.deleted_at.is_(None),
        or_(Employee.hire_date.is_(None), Employee.hire_date <= end),
        or_(Employee.end_date.is_(None), Employee.end_date >= start),
        or_(Employee.status == "active", Employee.end_date >= start))).all()
    total = Decimal(0)
    for e in employees:
        if e.id in taken:
            continue
        entries = db.scalars(select(EmployeeEntry).where(EmployeeEntry.employee_id == e.id,
                                                         EmployeeEntry.deleted_at.is_(None))).all()
        bonuses = sum((x.amount for x in entries if x.kind == "bonus" and x.month == run.month), Decimal(0))
        deductions = sum((x.amount for x in entries if x.kind == "deduction" and x.month == run.month), Decimal(0))
        unpaid = Decimal(0)
        for lv in db.scalars(select(Leave).where(Leave.employee_id == e.id, Leave.deleted_at.is_(None),
                                                 Leave.status == "approved", Leave.kind == "unpaid",
                                                 Leave.start_date <= end, Leave.end_date >= start)):
            span = (lv.end_date - lv.start_date).days + 1
            inside = (min(lv.end_date, end) - max(lv.start_date, start)).days + 1
            unpaid += (lv.days * inside / span) if span else Decimal(0)
        unpaid = unpaid.quantize(CENT)
        leave_cut = _money(e.base_salary / 30 * unpaid)
        gross = _money(e.base_salary + bonuses - deductions - leave_cut)
        repay = Decimal(0)
        room = max(gross, Decimal(0))
        for adv in sorted((x for x in entries if x.kind == "advance" and x.month <= run.month),
                          key=lambda x: x.entry_date):
            take = min(adv.installment or adv.amount, adv.amount - adv.repaid, room - repay)
            if take > 0:
                repay += take
        repay = _money(repay)
        slip = Payslip(run_id=run.id, employee_id=e.id, base_salary=e.base_salary, bonuses=bonuses,
                       deductions=deductions, unpaid_leave_days=unpaid, unpaid_leave_deduction=leave_cut,
                       advance_repayment=repay, gross=gross, net=_money(max(gross, Decimal(0)) - repay))
        db.add(slip)
        total += slip.net
    run.total = _money(total)


@router.get("/payroll-runs", response_model=Page[RunOut])
def list_runs(month: str | None = None, params: PageParams = Depends(), dc=Depends(require("hr.read"))):
    db, ctx = dc
    stmt = select(PayrollRun).where(PayrollRun.deleted_at.is_(None)).order_by(PayrollRun.month.desc(),
                                                                                PayrollRun.created_at.desc())
    stmt = branch_scope(stmt, ctx, "hr.read", PayrollRun.branch_id)
    if month:
        stmt = stmt.where(PayrollRun.month == month)
    return paginate(db, stmt, params, RunOut)


@router.post("/payroll-runs", response_model=RunOut, status_code=201)
def create_run(body: RunIn, dc=Depends(require("hr.payroll"))):
    db, ctx = dc
    ctx.require("hr.payroll", body.branch_id)
    branch = get_or_404(db, Branch, body.branch_id)
    if db.scalar(select(PayrollRun.id).where(PayrollRun.month == body.month, PayrollRun.branch_id == branch.id,
                                             PayrollRun.deleted_at.is_(None))):
        raise Conflict("This branch already has a payroll for this month", code="PAYROLL_EXISTS")
    run = PayrollRun(number=next_number(db, "payroll", "PR", branch.code), month=body.month, branch_id=branch.id,
                     notes=body.notes)
    db.add(run)
    db.flush()
    _calculate(db, run)
    audit(db, run, "create")
    db.commit()
    return _run_out(db, ctx, run)


@router.get("/payroll-runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, dc=Depends(require("hr.read"))):
    db, ctx = dc
    out = _run_out(db, ctx, _run(db, ctx, run_id, "hr.read"))
    db.commit()
    return out


@router.post("/payroll-runs/{run_id}/recalculate", response_model=RunOut)
def recalculate_run(run_id: uuid.UUID, dc=Depends(require("hr.payroll"))):
    db, ctx = dc
    run = _run(db, ctx, run_id, "hr.payroll")
    if run.status != "draft":
        raise Conflict("A paid payroll is closed", code="PAYROLL_PAID")
    _calculate(db, run)
    run.version += 1
    db.commit()
    return _run_out(db, ctx, run)


class PayIn(BaseModel):
    version: int
    cashbox_id: uuid.UUID
    method: str = Field("cash", pattern="^(cash|transfer|cheque|card)$")


@router.post("/payroll-runs/{run_id}/pay", response_model=RunOut)
def pay_run(run_id: uuid.UUID, body: PayIn, dc=Depends(require("hr.payroll"))):
    """صرف المرتبات: one payment per employee from the cashbox; advances are taken back; the run is closed."""
    from app.modules.treasury.models import Cashbox
    from app.modules.treasury.router import post_cash

    db, ctx = dc
    run = _run(db, ctx, run_id, "hr.payroll")
    check_version(run, body.version)
    if run.status != "draft":
        raise Conflict("Already paid", code="PAYROLL_PAID")
    box = get_or_404(db, Cashbox, body.cashbox_id)
    ctx.require("treasury.create", box.branch_id)
    _calculate(db, run)     # pay what the data says now
    db.flush()
    before = snapshot(run)
    slips = db.scalars(select(Payslip).where(Payslip.run_id == run.id)).all()
    for slip in slips:
        emp = db.get(Employee, slip.employee_id)
        if slip.net > 0:
            tx = post_cash(db, ctx, box, direction="out", amount=slip.net, method=body.method, party_type="employee",
                           party_id=emp.id, note=f"مرتب {run.month} {emp.code}")
            slip.cash_transaction_id = tx.id
        left = slip.advance_repayment
        for adv in db.scalars(select(EmployeeEntry).where(
                EmployeeEntry.employee_id == emp.id, EmployeeEntry.kind == "advance",
                EmployeeEntry.deleted_at.is_(None), EmployeeEntry.month <= run.month)
                .order_by(EmployeeEntry.entry_date)):
            take = min(adv.installment or adv.amount, adv.amount - adv.repaid, left)
            if take > 0:
                adv.repaid += take
                left -= take
        for x in db.scalars(select(EmployeeEntry).where(EmployeeEntry.employee_id == emp.id,
                                                        EmployeeEntry.kind.in_(("bonus", "deduction")),
                                                        EmployeeEntry.month == run.month,
                                                        EmployeeEntry.deleted_at.is_(None))):
            x.payslip_id = slip.id
    run.status, run.cashbox_id, run.paid_at = "paid", box.id, utcnow()
    audit(db, run, "update", before, note="paid")
    db.commit()
    return _run_out(db, ctx, run)


@router.delete("/payroll-runs/{run_id}", response_model=DeleteResult)
def delete_run(run_id: uuid.UUID, dc=Depends(require("hr.payroll"))):
    db, ctx = dc
    run = _run(db, ctx, run_id, "hr.payroll")
    if run.status != "draft":
        raise Conflict("A paid payroll cannot be deleted", code="PAYROLL_PAID")
    before = snapshot(run)
    run.deleted_at = utcnow()
    audit(db, run, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


@router.get("/employees/{eid}/payslips", response_model=list[PayslipOut])
def employee_payslips(eid: uuid.UUID, dc=Depends(require("hr.read"))):
    db, ctx = dc
    e = _employee(db, ctx, eid)
    rows = db.execute(select(Payslip, PayrollRun.month).join(PayrollRun, PayrollRun.id == Payslip.run_id).where(
        Payslip.employee_id == e.id, PayrollRun.deleted_at.is_(None), PayrollRun.status == "paid")
        .order_by(PayrollRun.month.desc())).all()
    out = []
    for slip, month in rows:
        o = PayslipOut.model_validate(slip)
        o.month, o.employee_code, o.employee_name, o.job_title = month, e.code, e.full_name, e.job_title
        out.append(o)
    return out


def salesperson_for(db, ctx, employee_id: uuid.UUID | None) -> uuid.UUID | None:
    """The salesperson of a sale: the one chosen, else the employee linked to the user who makes it."""
    if employee_id is not None:
        return get_or_404(db, Employee, employee_id).id
    return db.scalar(select(Employee.id).where(Employee.user_id == ctx.user_id, Employee.deleted_at.is_(None),
                                               Employee.status == "active"))
