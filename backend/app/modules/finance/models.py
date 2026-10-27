from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, SoftDeleteMixin

ASSET_CATEGORIES = {"vehicle": "عربيات", "machine": "ماكينات", "building": "مباني وأراضي", "equipment": "معدات وعدد",
                    "furniture": "أثاث وأجهزة", "other": "أخرى"}


class CompanyAsset(Base, Entity, SoftDeleteMixin):
    """أصل من أصول الشركة. Counted in the capital at its value (no depreciation) until it is sold / written off."""
    __tablename__ = "company_assets"

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), default="other")
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")   # active | disposed
    disposed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
