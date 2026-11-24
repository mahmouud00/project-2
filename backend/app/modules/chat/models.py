"""الشات بين المستخدمين، وتفويض الصلاحيات."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Entity, IdMixin, TenantMixin, utcnow


class ChatConversation(Base, Entity):
    """محادثة: بين اتنين (direct, direct_key = the two user ids sorted) أو جروب باسم."""
    __tablename__ = "chat_conversations"
    __table_args__ = (UniqueConstraint("company_id", "direct_key"),)

    kind: Mapped[str] = mapped_column(String(10), default="direct")      # direct | group
    title: Mapped[str] = mapped_column(String(120), default="")
    direct_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ChatMember(Base, IdMixin, TenantMixin):
    __tablename__ = "chat_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_conversations.id",
                                                       ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatMessage(Base, IdMixin, TenantMixin):
    """A message: text and / or one file (picture, PDF, anything) kept by its content hash like the media files,
    served only to the conversation's members."""
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation_at", "conversation_id", "at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_conversations.id",
                                                       ondelete="CASCADE"))
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    body: Mapped[str] = mapped_column(Text, default="")
    file_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PermissionDelegation(Base, Entity):
    """تفويض: from_user gives all their permissions (in their branches) to to_user between starts_at and ends_at.
    Not passed on again (a delegate cannot delegate what was delegated to them)."""
    __tablename__ = "permission_delegations"

    from_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    to_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
