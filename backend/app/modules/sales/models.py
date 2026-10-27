from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, SoftDeleteMixin, TenantMixin


class DocumentSequence(Base, IdMixin, TenantMixin):
    __tablename__ = "document_sequences"
    __table_args__ = (UniqueConstraint("company_id", "key"),)

    key: Mapped[str] = mapped_column(String(80))
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class PriceList(Base, Entity):
    """قائمة أسعار (عميل نهائي / تاجر / مقاول): cost-plus margin, optional per-m² prices."""
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    customer_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # default list for that type
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=Decimal(0))
    labor_cost_per_m2: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal(0))
    min_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceListItem(Base, Entity):
    """Override for one model (or a whole system): margin or a fixed price per m²."""
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "model_id", "system_id"),)

    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("price_lists.id",
                                                                                    ondelete="CASCADE"), index=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"), nullable=True)
    system_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"),
                                                        nullable=True)
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    price_per_m2: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class Quotation(Base, Entity, SoftDeleteMixin):
    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("company_id", "number"),)

    number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    survey_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("site_surveys.id"), nullable=True)
    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("price_lists.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|sent|accepted|rejected|expired
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=Decimal(0))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    notes: Mapped[str] = mapped_column(Text, default="")
    terms: Mapped[str] = mapped_column(Text, default="")
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id"),
                                                             nullable=True, index=True)


class QuotationLine(Base, Entity):
    __tablename__ = "quotation_lines"

    quotation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"),
                                                    index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(200), default="")
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"))
    formula_set_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("formula_set_versions.id"))
    opening_width_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    opening_height_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # ارتفاع كلي (from the survey): when set, the area for the price is width × total height
    total_height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    top_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"),
                                                           nullable=True)   # model of the arch (أرج)
    # the arch is a separate unit (own frame): a line of its own, made and costed with its model, priced
    # inside its parent line (price 0 here); managed through the parent only
    parent_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quotation_lines.id",
                                                             ondelete="CASCADE"), nullable=True, index=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    color_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    glass_material_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    area_m2: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    manual_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    price_per_m2: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)    # typed by the user
    # area of one unit used for the price per m², after the company's minimum (e.g. 1 m²)
    billed_area_m2: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal(0), server_default="0")
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    calc: Mapped[dict] = mapped_column(JSONB, default=dict)      # frozen engine result + calibration used
    cost_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
