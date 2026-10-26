from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin


class Supplier(Base, Entity, SoftDeleteMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    __pii__ = ("contact_name", "phone", "email", "address")

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class PurchaseOrder(Base, Entity, SoftDeleteMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|ordered|partial|received|cancelled
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    received_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    notes: Mapped[str] = mapped_column(Text, default="")
    # a goods order for one customer's work order (from its cut list, glass and accessories)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                            nullable=True, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)


class PurchaseOrderLine(Base, Entity):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id",
                                                                                        ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[str] = mapped_column(String(80))
    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(16, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(16, 4), default=Decimal(0))
