"""طلبات الحذف: a deleted thing waits 30 days (with a countdown) before it is erased; whoever holds the permanent
delete permission can erase it at once, and the one who asked or that holder can take it back."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, utcnow


class DeletionRequest(Base, Entity):
    __tablename__ = "deletion_requests"
    __table_args__ = (Index("uq_deletion_requests_pending", "company_id", "kind", "target_id", unique=True,
                            postgresql_where=text("status = 'pending'")),)

    kind: Mapped[str] = mapped_column(String(40))             # the delete address, e.g. "library/materials"
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    label: Mapped[str] = mapped_column(String(200), default="")   # what it is (a code or number, never a person)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")    # pending | done | cancelled | failed
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")        # why it could not be deleted
