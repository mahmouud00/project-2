from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin

CUSTOMER_TYPES = ("end", "dealer", "contractor")


class Customer(Base, Entity, SoftDeleteMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    __pii__ = ("name", "phone", "phone2", "email", "address", "national_id", "notes")

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    customer_type: Mapped[str] = mapped_column(String(20), default="end")
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    phone2: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("price_lists.id"),
                                                            nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    anonymized: Mapped[bool] = mapped_column(default=False)


class SiteSurvey(Base, Entity, SoftDeleteMixin):
    """معاينة: visit to measure the openings."""
    __tablename__ = "site_surveys"
    __pii__ = ("address",)

    number: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    survey_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    surveyor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | cancelled
    notes: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="window", server_default="window")  # window | shutter
    floor: Mapped[str | None] = mapped_column(String(40), nullable=True)                     # الدور
    technician: Mapped[str | None] = mapped_column(String(120), nullable=True)               # الفني


class SurveyOpening(Base, Entity):
    """One measured opening. The site size is stored as measured; the
    manufacturing size is derived by the engine (clearance subtracted)."""
    __tablename__ = "survey_openings"

    survey_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("site_surveys.id", ondelete="CASCADE"),
                                                 index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str] = mapped_column(String(200), default="")  # e.g. مطبخ، صالة
    opening_width_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    opening_height_mm: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    color_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    glass_material_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # survey sheet columns (windows/doors): total height, sliding/hinged, glass, insect screen, application
    total_height_mm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)   # ارتفاع كلي
    unit_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)                 # sliding | hinged
    color_text: Mapped[str | None] = mapped_column(String(80), nullable=True)                # colour as written on site
    glass_layers: Mapped[str | None] = mapped_column(String(10), nullable=True)              # single | double
    glass_color: Mapped[str | None] = mapped_column(String(80), nullable=True)
    screen_type: Mapped[str | None] = mapped_column(String(20), nullable=True)               # sliding | pleated | hinged | fixed
    application: Mapped[str] = mapped_column(Text, default="", server_default="")           # التطبيق
    # shutters
    installation_method: Mapped[str | None] = mapped_column(String(120), nullable=True)      # طريقة التركيب
    motor_type: Mapped[str | None] = mapped_column(String(120), nullable=True)               # نوع الموتور
