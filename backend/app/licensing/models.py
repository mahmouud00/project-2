from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity


class Subscription(Base, Entity):
    """Online mode: what a company has paid for. One active row per company."""
    __tablename__ = "subscriptions"

    modules: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    max_users: Mapped[int] = mapped_column(Integer, default=5)
    max_branches: Mapped[int] = mapped_column(Integer, default=1)
    max_devices: Mapped[int] = mapped_column(Integer, default=5)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
