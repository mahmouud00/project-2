from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, TenantMixin, utcnow


class Warehouse(Base, Entity):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StockBalance(Base, IdMixin, TenantMixin):
    """Current quantity per warehouse and SKU (row-locked on every movement)."""
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("warehouse_id", "sku"),)

    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80))
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id"), nullable=True)
    unit: Mapped[str] = mapped_column(String(10), default="")
    qty: Mapped[Decimal] = mapped_column(Numeric(16, 4), default=Decimal(0))
    avg_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)


class StockMovement(Base, IdMixin, TenantMixin):
    """Immutable ledger line. Corrections are new movements, never edits."""
    __tablename__ = "stock_movements"

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id"), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(16, 4))  # + in / - out
    unit: Mapped[str] = mapped_column(String(10), default="")
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # receipt|issue|adjustment|transfer_out|transfer_in|return
    ref_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class StockTransfer(Base, Entity):
    __tablename__ = "stock_transfers"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | received | cancelled
    lines: Mapped[list] = mapped_column(JSONB, default=list)         # [{"sku", "qty"}]
    note: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
