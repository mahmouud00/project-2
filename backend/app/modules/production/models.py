from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, SoftDeleteMixin, TenantMixin, utcnow

# Order of the workflow; "cancelled" is reachable from any stage before delivery.
STAGES = ("survey", "quotation", "approved", "manufacturing", "assembly", "quality", "delivered")
STAGE_NAMES = {"survey": "معاينة", "quotation": "عرض سعر", "approved": "موافقة وعربون", "manufacturing": "تصنيع",
               "assembly": "تجميع", "quality": "جودة", "delivered": "تسليم", "cancelled": "ملغي"}


class WorkOrder(Base, Entity, SoftDeleteMixin):
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id"), nullable=True)
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"),
                                                             nullable=True, index=True)
    # تأكيد الحسابات على البيعة: the order cannot reach "approved" (nor manufacturing) before it
    sale_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")  # pending|approved|rejected
    sale_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sale_approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sale_approval_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    stage: Mapped[str] = mapped_column(String(20), default="survey", index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    deposit_required: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    outputs: Mapped[dict] = mapped_column(JSONB, default=dict)   # manufacturing outputs (frozen at production start)
    outputs_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkOrderItem(Base, Entity):
    """Frozen copy of what is manufactured: inputs, formula version, engine result."""
    __tablename__ = "work_order_items"

    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"),
                                                     index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(200), default="")
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"))
    formula_set_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("formula_set_versions.id"))
    opening_width_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    opening_height_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    color_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    glass_material_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    calc: Mapped[dict] = mapped_column(JSONB, default=dict)


class WorkOrderStageLog(Base, IdMixin, TenantMixin):
    __tablename__ = "work_order_stage_log"

    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"),
                                                     index=True)
    from_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class Offcut(Base, Entity):
    """فُضلة قطاع (بعد التقطيع) أطول من «أقل فُضلة تتشال»: المخزون الوحيد في المصنع. Used first by later orders."""
    __tablename__ = "offcuts"

    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)          # the profile in its colour
    material_code: Mapped[str] = mapped_column(String(60))
    length_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))        # clean usable length
    status: Mapped[str] = mapped_column(String(20), default="available", index=True)  # available | used | scrapped
    source_work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                                   nullable=True)
    used_work_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_orders.id"),
                                                                 nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
