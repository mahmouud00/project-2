from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin

DEPARTMENTS = {"sales": "مبيعات", "production": "إنتاج", "installation": "تركيبات", "survey": "معاينات",
               "accounts": "حسابات", "hr": "موارد بشرية", "admin": "إدارة", "other": "أخرى"}


class Employee(Base, Entity, SoftDeleteMixin):
    """A person on the payroll (not necessarily a user of the system)."""
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    __pii__ = ("full_name", "phone", "national_id", "address")

    code: Mapped[str] = mapped_column(String(40))
    full_name: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str] = mapped_column(String(120), default="")
    department: Mapped[str] = mapped_column(String(20), default="other", index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
                                                      index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")   # active | left
    base_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    annual_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(21))
    notes: Mapped[str] = mapped_column(Text, default="")
    attendance_pin: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)   # رقمه على جهاز البصمة
    pay_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pay_policies.id"),
                                                            nullable=True, index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)


class EmployeeEntry(Base, Entity, SoftDeleteMixin):
    """حافز / خصم / سلفة. Bonuses and deductions apply to the salary of `month`; an advance is paid out of a
    cashbox now and taken back from the following salaries (`installment` per month)."""
    __tablename__ = "employee_entries"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))            # bonus | deduction | advance | piecework
    entry_date: Mapped[date] = mapped_column(Date)
    month: Mapped[str] = mapped_column(String(7), index=True)   # YYYY-MM: the salary it applies to / first repayment
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    installment: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)   # advance: per month
    repaid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))          # advance: taken back so far
    cash_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                                  ForeignKey("cash_transactions.id"), nullable=True)
    payslip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)   # bonus/deduction paid
    note: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)   # piecework: openings
    rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)       # piecework: per opening


class Leave(Base, Entity, SoftDeleteMixin):
    __tablename__ = "employee_leaves"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))            # annual | sick | unpaid | other
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), default="approved")   # requested | approved | rejected
    note: Mapped[str] = mapped_column(Text, default="")


class PayrollRun(Base, Entity, SoftDeleteMixin):
    """كشف مرتبات شهر لفرع. Draft: recalculated freely. Paid: frozen, one cash payment per employee."""
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    month: Mapped[str] = mapped_column(String(7), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")   # draft | paid
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    cashbox_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cashboxes.id"),
                                                         nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Payslip(Base, Entity):
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("run_id", "employee_id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"),
                                              index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    bonuses: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    unpaid_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(0))
    unpaid_leave_deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    advance_repayment: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))   # cost to the company
    net: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))     # handed to the employee
    cash_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                                  ForeignKey("cash_transactions.id"), nullable=True)
    # from the attendance and the pay policy (0 when the employee has no policy)
    present_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(0))
    absent_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(0))
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    attendance_deduction: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    allowances: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))   # travel / holidays / meals / transport
    piecework: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    collections: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    commission_forced: Mapped[bool] = mapped_column(Boolean, default=False)   # the manager allowed it under the minimum
    review_days: Mapped[int] = mapped_column(Integer, default=0)              # days the attendance review must look at
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class PayPolicy(Base, Entity, SoftDeleteMixin):
    """سياسة مرتبات وحضور (الإدارة، المبيعات، المصنع، التركيبات…): every number in `rules` is the company's own and
    editable; see app.modules.hr.policy.Rules for what each one means."""
    __tablename__ = "pay_policies"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class WorkZone(Base, Entity):
    """A place counted as «inside» (القاهرة، الجيزة، العاشر، العبور…): an installation there is a normal installation
    day (with its transport allowance); anywhere outside every zone is a travel day."""
    __tablename__ = "work_zones"

    name: Mapped[str] = mapped_column(String(120))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    radius_km: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    transport_allowance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PublicHoliday(Base, Entity):
    __tablename__ = "public_holidays"
    __table_args__ = (UniqueConstraint("company_id", "day"),)

    day: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(120), default="")


class AttendanceDay(Base, Entity):
    """What HR (or the installations manager) decided about one employee's day: its kind when the automatic one is
    wrong, an excuse (إذن / غياب بتبليغ), times written by hand, which morning punch counts when there are two
    (device and app). Nothing here changes the punches themselves."""
    __tablename__ = "attendance_days"
    __table_args__ = (UniqueConstraint("company_id", "employee_id", "day"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)      # normal | install | travel | off
    excuse: Mapped[str] = mapped_column(String(20), default="none")          # none | permission | notified | excused
    permission_minutes: Mapped[int] = mapped_column(Integer, default=0)
    manual_in: Mapped[time | None] = mapped_column(Time, nullable=True)
    manual_out: Mapped[time | None] = mapped_column(Time, nullable=True)
    start_source: Mapped[str | None] = mapped_column(String(10), nullable=True)   # device | app (two morning punches)
    conflict_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class AttendanceDevice(Base, Entity):
    """جهاز بصمة (ZKTeco ADMS / push). It identifies itself by its serial number only, so a serial belongs to one
    company on the whole server. A stopped device (is_active false) is answered but what it sends is not kept."""
    __tablename__ = "attendance_devices"
    __table_args__ = (UniqueConstraint("serial"),)

    serial: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120), default="")
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_punch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    attlog_stamp: Mapped[str | None] = mapped_column(String(40), nullable=True)   # where the device continues from
    info: Mapped[str] = mapped_column(String(200), default="")                    # firmware / push version


class AttendancePunch(Base, Entity):
    """One fingerprint / face punch as the device sent it. `punched_at` is the device's own clock (factory local
    time, no time zone). Never edited: a wrong punch is answered in the attendance review, not here."""
    __tablename__ = "attendance_punches"
    __table_args__ = (UniqueConstraint("company_id", "device_serial", "pin", "punched_at"),)

    device_serial: Mapped[str] = mapped_column(String(40))
    pin: Mapped[str] = mapped_column(String(20), index=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"),
                                                          nullable=True, index=True)
    punched_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), index=True)
    state: Mapped[int] = mapped_column(Integer, default=0)     # device status: 0 in, 1 out, 2/3 break, 4/5 overtime
    verify: Mapped[int] = mapped_column(Integer, default=0)    # 1 finger, 15 face, 3/4 password / card ...
    source: Mapped[str] = mapped_column(String(10), default="device")   # device | app (the phone, with its place)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
