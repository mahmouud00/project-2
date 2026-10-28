"""Catalogue library.

Rows owned by PLATFORM_COMPANY_ID are the MYTech library: authored once by the
vendor, shipped to every customer (signed package offline, shared rows online)
and readable by all companies. A company can also create its own private
systems in the same tables (company_id = its own id).

Company-specific adjustments never live in these rows: see CompanyCalibration,
CompanyConstantOverride and CompanyMaterialSetting (tenant tables), so a
library update can never overwrite them.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin, utcnow

MATERIAL_TYPES = ("upvc", "shutter", "aluminum")
MATERIAL_KINDS = ("profile", "reinforcement", "accessory", "glass", "gasket", "consumable", "panel", "other")
UNITS = ("m", "pcs", "set", "roll", "m2", "kg", "l")
STATUSES = ("approved", "trial")


class LibraryEntity(Entity):
    __tenancy__ = "library"


class MediaFile(Base, LibraryEntity):
    __tablename__ = "media_files"

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(60))
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)


class Color(Base, LibraryEntity):
    __tablename__ = "colors"
    __table_args__ = (UniqueConstraint("company_id", "code"),)

    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    hex: Mapped[str | None] = mapped_column(String(9), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProfileSystem(Base, LibraryEntity, SoftDeleteMixin):
    __tablename__ = "profile_systems"
    # unique among the rows not deleted (a deleted one kept for old orders may share the code with a new one)
    __table_args__ = (Index("uq_profile_systems_company_id_code", "company_id", "code", unique=True,
                            postgresql_where=text("deleted_at IS NULL")),)

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    supplier: Mapped[str] = mapped_column(String(200), default="")
    material_type: Mapped[str] = mapped_column(String(20))  # upvc | shutter | aluminum
    unit: Mapped[str] = mapped_column(String(4), default="mm")  # unit the formulas are written in
    rounding_step_mm: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    rounding_mode: Mapped[str] = mapped_column(String(10), default="half_up")
    status: Mapped[str] = mapped_column(String(10), default="trial")
    description: Mapped[str] = mapped_column(Text, default="")
    image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class SystemConstant(Base, LibraryEntity):
    """Named constant of a system (e.g. weld_allowance, glass_clearance)."""
    __tablename__ = "system_constants"
    __table_args__ = (UniqueConstraint("system_id", "name"),)

    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Material(Base, LibraryEntity, SoftDeleteMixin):
    __tablename__ = "materials"
    __table_args__ = (Index("uq_materials_company_id_code", "company_id", "code", unique=True,
                            postgresql_where=text("deleted_at IS NULL")),)

    system_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"),
                                                        nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(20), default="profile")
    unit: Mapped[str] = mapped_column(String(10), default="m")
    bar_length_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_piece_mm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    weight_kg_per_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    reference_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MaterialVariant(Base, LibraryEntity):
    """Colour variant of a material with its own stock code (SKU)."""
    __tablename__ = "material_variants"
    __table_args__ = (UniqueConstraint("material_id", "color_code"), UniqueConstraint("company_id", "sku"))

    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id"), index=True)
    color_code: Mapped[str] = mapped_column(String(20))
    sku: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(300), default="")
    reference_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductModel(Base, LibraryEntity, SoftDeleteMixin):
    """A window/door/shutter model of a system with its full definition
    (parameters, formulas, cut pieces per material with their deductions,
    glass, accessories, validations, drawing) as one JSON document."""
    __tablename__ = "product_models"
    __table_args__ = (Index("uq_product_models_system_id_code", "system_id", "code", unique=True,
                            postgresql_where=text("deleted_at IS NULL")),)

    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(30), default="window")
    description: Mapped[str] = mapped_column(Text, default="")
    image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_files.id"), nullable=True)
    # the model's picture in each colour {colour code: media id}; image_id is used for other colours
    color_images: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(10), default="trial")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    definition: Mapped[dict] = mapped_column(JSONB, default=dict)


class ModelTestCase(Base, LibraryEntity):
    """Reference result verified by the vendor. Publishing fails if any case drifts > 0.1 mm."""
    __tablename__ = "model_test_cases"

    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product_models.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    opening_width_mm: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    opening_height_mm: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"values": {key: mm}, "pieces": {key: mm}, "glass": {key: [w, h]}, "accessories": {key: qty}}
    expected: Mapped[dict] = mapped_column(JSONB, default=dict)


class FormulaSetVersion(Base, LibraryEntity):
    """Immutable published snapshot of a system (constants + materials + models).
    Work orders store the id of the version they were calculated with."""
    __tablename__ = "formula_set_versions"
    __table_args__ = (UniqueConstraint("system_id", "version_no"),)

    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- company-private adjustments
class CompanyCalibration(Base, Entity):
    """+/- delta a company applies to a system constant (e.g. +1 mm weld)."""
    __tablename__ = "company_calibrations"
    __table_args__ = (UniqueConstraint("company_id", "system_id", "constant_name"),)

    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"), index=True)
    constant_name: Mapped[str] = mapped_column(String(80))
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    note: Mapped[str] = mapped_column(Text, default="")


class CompanyConstantOverride(Base, Entity):
    """A company's own value for a library constant (replaces the library value)."""
    __tablename__ = "company_constant_overrides"
    __table_args__ = (UniqueConstraint("company_id", "system_id", "constant_name"),)

    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile_systems.id"), index=True)
    constant_name: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    note: Mapped[str] = mapped_column(Text, default="")


class CompanyMaterialSetting(Base, Entity):
    """A company's price / internal code / visibility for a library material."""
    __tablename__ = "company_material_settings"
    __table_args__ = (UniqueConstraint("company_id", "material_id", "color_code"),)

    material_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("materials.id"), index=True)
    color_code: Mapped[str] = mapped_column(String(20), default="")  # "" = all colours
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    # خصم المورد على الخامة دي (بيتغير): the cost used is unit_cost × (1 − discount / 100)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    internal_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class LibraryImport(Base, Entity):
    """Log of library packages a company previewed/applied."""
    __tablename__ = "library_imports"

    package_id: Mapped[str] = mapped_column(String(64))
    package_created_at: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="previewed")  # previewed | applied | rejected
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
