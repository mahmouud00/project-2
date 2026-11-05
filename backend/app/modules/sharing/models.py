"""Links a customer opens without an account: a quotation (to read and approve or ask for a change) or an invoice
(to read). Only the SHA-256 of the link's token is stored, so the database alone cannot rebuild a link."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity


class DocumentShare(Base, Entity):
    __tablename__ = "document_shares"

    doc_type: Mapped[str] = mapped_column(String(20))                 # quotation | invoice
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    response: Mapped[str | None] = mapped_column(String(20), nullable=True)   # accepted | change_requested
    response_note: Mapped[str] = mapped_column(Text, default="")
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
