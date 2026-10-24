from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, TenantMixin, utcnow


class Cashbox(Base, Entity):
    __tablename__ = "cashboxes"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CashTransaction(Base, IdMixin, TenantMixin):
    """Immutable. A mistake is corrected by a reversing transaction."""
    __tablename__ = "cash_transactions"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    cashbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cashboxes.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))   # in | out
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String(20), default="cash")  # cash | transfer | cheque | card
    party_type: Mapped[str] = mapped_column(String(20))  # customer | supplier | other
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                            nullable=True, index=True)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"),
                                                                nullable=True, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"),
                                                         nullable=True, index=True)
    reference: Mapped[str] = mapped_column(String(100), default="")  # cheque / transfer number
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cash_transactions.id"),
                                                          nullable=True)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
