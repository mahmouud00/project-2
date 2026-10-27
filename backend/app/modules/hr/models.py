from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
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


class EmployeeEntry(Base, Entity, SoftDeleteMixin):
    """حافز / خصم / سلفة. Bonuses and deductions apply to the salary of `month`; an advance is paid out of a
    cashbox now and taken back from the following salaries (`installment` per month)."""
    __tablename__ = "employee_entries"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))            # bonus | deduction | advance
    entry_date: Mapped[date] = mapped_column(Date)
    month: Mapped[str] = mapped_column(String(7), index=True)   # YYYY-MM: the salary it applies to / first repayment
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    installment: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)   # advance: per month
    repaid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))          # advance: taken back so far
    cash_transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                                  ForeignKey("cash_transactions.id"), nullable=True)
    payslip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)   # bonus/deduction paid
    note: Mapped[str] = mapped_column(Text, default="")


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
