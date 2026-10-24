from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin


class Invoice(Base, Entity, SoftDeleteMixin):
    """Customer invoice. Editable while draft; numbered and locked when issued.
    An issued invoice is never edited or deleted, only cancelled with a reason."""
    __tablename__ = "invoices"

    number: Mapped[str | None] = mapped_column(String(40), nullable=True)  # given at issue (gap-free)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                            nullable=True, index=True)
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | issued | cancelled
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lines_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))       # after line discounts
    lines_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))   # invoice-level
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal(0))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(Text, default="")


class InvoiceLine(Base, Entity):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"),
                                                  index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20), default="product")  # product (window/door) | service | other
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"), nullable=True)
    model_name: Mapped[str] = mapped_column(String(300), default="")
    model_image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    opening_width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    opening_height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)   # manufacturing size
    height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    color_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    glass_material_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    drawing: Mapped[list] = mapped_column(JSONB, default=list)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal(0))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))   # computed
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))        # after discount
