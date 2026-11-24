"""الشات بين المستخدمين (مع الصور والملفات)، الأونلاين وآخر ظهور، وتفويض الصلاحيات.

Every user of the company can chat with every other (direct) or in groups; a conversation is seen only by its
members. Files are kept by their content hash (like the media files) and served only to members. Online = seen in
the last 3 minutes (any request of the program counts; the chat screen asks every few seconds).

Delegation: a user gives all their permissions to another user of the company from a time to a time; the
receiver holds them only in that window, and cannot pass them on. The giver, the receiver and an admin
(users.manage) can see and stop it.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.core.audit import audit, snapshot
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import utcnow
from app.modules.chat.models import ChatConversation, ChatMember, ChatMessage, PermissionDelegation
from app.modules.org.models import User
from app.tenancy.context import get_db_and_ctx

router = APIRouter(tags=["chat"])
ONLINE = timedelta(minutes=3)
MAX_FILE = 25 * 1024 * 1024


def _online(u: User) -> bool:
    return bool(u.last_seen_at and datetime.now(timezone.utc) - u.last_seen_at < ONLINE)


class PersonOut(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    online: bool
    last_seen_at: datetime | None


def _person(u: User) -> PersonOut:
    return PersonOut(id=u.id, username=u.username, full_name=u.full_name or u.username, online=_online(u),
                     last_seen_at=u.last_seen_at)


@router.get("/chat/people", response_model=list[PersonOut])
def people(dc=Depends(get_db_and_ctx)):
    """Everyone in the company (active), with online / last seen."""
    db, ctx = dc
    users = db.scalars(select(User).where(User.is_active.is_(True), User.deleted_at.is_(None))
                       .order_by(User.full_name)).all()
    return [_person(u) for u in users if u.id != ctx.user_id]


# ---------------------------------------------------------------- conversations
class ConversationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    members: list[PersonOut]
    last_message: str | None = None
    last_message_at: datetime | None = None
    unread: int = 0


def _member(db, ctx, conversation_id) -> ChatMember:
    m = db.scalar(select(ChatMember).where(ChatMember.conversation_id == conversation_id,
                                           ChatMember.user_id == ctx.user_id))
    if m is None:
        raise NotFound("Conversation not found")
    return m


def _conv_out(db, ctx, c: ChatConversation, me: ChatMember | None = None) -> ConversationOut:
    users = db.scalars(select(User).join(ChatMember, ChatMember.user_id == User.id)
                       .where(ChatMember.conversation_id == c.id)).all()
    others = [u for u in users if u.id != ctx.user_id]
    title = c.title or "، ".join(u.full_name or u.username for u in others) or "أنا"
    last = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == c.id, ChatMessage.deleted_at.is_(None))
                     .order_by(ChatMessage.at.desc()).limit(1))
    me = me or _member(db, ctx, c.id)
    unread = db.scalar(select(func.count()).select_from(ChatMessage).where(
        ChatMessage.conversation_id == c.id, ChatMessage.sender_id != ctx.user_id, ChatMessage.deleted_at.is_(None),
        ChatMessage.at > (me.last_read_at or datetime(2000, 1, 1, tzinfo=timezone.utc)))) or 0
    preview = None
    if last is not None:
        preview = last.body or (f"📎 {last.file_name}" if last.file_name else "")
    return ConversationOut(id=c.id, kind=c.kind, title=title, members=[_person(u) for u in users],
                           last_message=preview, last_message_at=c.last_message_at, unread=unread)


@router.get("/chat/conversations", response_model=list[ConversationOut])
def conversations(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    rows = db.execute(select(ChatConversation, ChatMember).join(ChatMember, ChatMember.conversation_id == ChatConversation.id)
                      .where(ChatMember.user_id == ctx.user_id)
                      .order_by(ChatConversation.last_message_at.desc().nulls_last())).all()
    return [_conv_out(db, ctx, c, m) for c, m in rows]


@router.get("/chat/unread")
def unread(dc=Depends(get_db_and_ctx)):
    """For the badge: how many unread messages in all my conversations."""
    db, ctx = dc
    total = db.scalar(select(func.count()).select_from(ChatMessage).join(
        ChatMember, and_(ChatMember.conversation_id == ChatMessage.conversation_id, ChatMember.user_id == ctx.user_id))
        .where(ChatMessage.sender_id != ctx.user_id, ChatMessage.deleted_at.is_(None),
               or_(ChatMember.last_read_at.is_(None), ChatMessage.at > ChatMember.last_read_at))) or 0
    return {"unread": total}


@router.post("/chat/direct/{user_id}", response_model=ConversationOut)
def direct(user_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    """The conversation with this person (made the first time)."""
    db, ctx = dc
    other = db.get(User, user_id)
    if other is None or other.deleted_at is not None or user_id == ctx.user_id:
        raise NotFound("User not found")
    key = ":".join(sorted([str(ctx.user_id), str(user_id)]))
    c = db.scalar(select(ChatConversation).where(ChatConversation.direct_key == key))
    if c is None:
        c = ChatConversation(kind="direct", title="", direct_key=key)
        db.add(c)
        db.flush()
        for uid in (ctx.user_id, user_id):
            db.add(ChatMember(conversation_id=c.id, user_id=uid))
        db.commit()
    return _conv_out(db, ctx, c)


class GroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    user_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/chat/groups", response_model=ConversationOut, status_code=201)
def group(body: GroupIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    ids = {ctx.user_id, *body.user_ids}
    found = set(db.scalars(select(User.id).where(User.id.in_(ids), User.deleted_at.is_(None))))
    if found != ids:
        raise ValidationFailed("Unknown user", code="USER_UNKNOWN")
    c = ChatConversation(kind="group", title=body.title.strip())
    db.add(c)
    db.flush()
    for uid in ids:
        db.add(ChatMember(conversation_id=c.id, user_id=uid))
    db.commit()
    return _conv_out(db, ctx, c)


# ---------------------------------------------------------------- messages
class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    at: datetime
    body: str
    file_name: str | None
    file_mime: str | None
    file_size: int | None
    file_url: str | None = None
    mine: bool = False


def _msg_out(ctx, m: ChatMessage) -> MessageOut:
    out = MessageOut(id=m.id, sender_id=m.sender_id, at=m.at, body=m.body, file_name=m.file_name,
                     file_mime=m.file_mime, file_size=m.file_size, mine=m.sender_id == ctx.user_id)
    if m.file_sha:
        out.file_url = f"/api/v1/chat/files/{m.id}"
    return out


@router.get("/chat/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def messages(conversation_id: uuid.UUID, after: datetime | None = None, before: datetime | None = None,
             limit: int = 50, dc=Depends(get_db_and_ctx)):
    """Newest first page (or the ones after `after`, to poll new ones; `before` for older); oldest first."""
    db, ctx = dc
    me = _member(db, ctx, conversation_id)
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id, ChatMessage.deleted_at.is_(None))
    if after is not None:
        rows = db.scalars(stmt.where(ChatMessage.at > after).order_by(ChatMessage.at).limit(200)).all()
    else:
        if before is not None:
            stmt = stmt.where(ChatMessage.at < before)
        rows = list(reversed(db.scalars(stmt.order_by(ChatMessage.at.desc()).limit(min(max(limit, 1), 200))).all()))
    if rows and (me.last_read_at is None or rows[-1].at > me.last_read_at):
        me.last_read_at = rows[-1].at
        db.commit()
    return [_msg_out(ctx, m) for m in rows]


def _store(data: bytes) -> str:
    from app.modules.library.router import media_path

    sha = hashlib.sha256(data).hexdigest()
    path = media_path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return sha


def _post(db, ctx, conversation_id, body: str, file: tuple[bytes, str, str] | None) -> MessageOut:
    from app.modules.notifications.router import alert

    _member(db, ctx, conversation_id)
    body = (body or "").strip()
    if not body and file is None:
        raise ValidationFailed("Write a message or choose a file", code="EMPTY_MESSAGE")
    m = ChatMessage(conversation_id=conversation_id, sender_id=ctx.user_id, at=utcnow(), body=body[:8000])
    if file is not None:
        data, name, mime = file
        m.file_sha, m.file_name, m.file_mime, m.file_size = _store(data), name[:255], mime[:100], len(data)
    db.add(m)
    c = db.get(ChatConversation, conversation_id)
    c.last_message_at = m.at
    me = _member(db, ctx, conversation_id)
    me.last_read_at = m.at
    db.flush()
    sender = db.get(User, ctx.user_id)
    others = set(db.scalars(select(ChatMember.user_id).where(ChatMember.conversation_id == conversation_id,
                                                           ChatMember.user_id != ctx.user_id)))
    who = sender.full_name or sender.username
    alert(db, ctx, "chat", None, f"رسالة من {who}" + (f" في {c.title}" if c.title else ""),
          (body[:120] or f"📎 {m.file_name}"), f"chat?c={conversation_id}", users=others)
    from app.ops.events import notify
    notify(db, ctx.company_id, "chat_messages", conversation_id, "create")
    db.commit()
    return _msg_out(ctx, m)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


@router.post("/chat/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def send(conversation_id: uuid.UUID, body: MessageIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    return _post(db, ctx, conversation_id, body.body, None)


@router.post("/chat/conversations/{conversation_id}/files", response_model=MessageOut, status_code=201)
async def send_file(conversation_id: uuid.UUID, file: UploadFile, caption: str = "", dc=Depends(get_db_and_ctx)):
    """A picture or any file (up to 25 MB), with an optional caption."""
    db, ctx = dc
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValidationFailed("File larger than 25 MB", code="FILE_TOO_LARGE")
    if not data:
        raise ValidationFailed("Empty file", code="FILE_EMPTY")
    mime = (file.content_type or "application/octet-stream").split(";")[0]
    return _post(db, ctx, conversation_id, caption, (data, file.filename or "file", mime))


@router.get("/chat/files/{message_id}")
def chat_file(message_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    from app.modules.library.router import media_path

    db, ctx = dc
    m = db.get(ChatMessage, message_id)
    if m is None or m.deleted_at is not None or not m.file_sha:
        raise NotFound("File not found")
    _member(db, ctx, m.conversation_id)
    path = media_path(m.file_sha)
    if not path.exists():
        raise NotFound("File not found")
    inline = (m.file_mime or "").startswith("image/")
    return FileResponse(path, media_type=m.file_mime or "application/octet-stream", filename=m.file_name,
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/chat/messages/{message_id}", status_code=204)
def delete_message(message_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    """Only the sender takes back their own message."""
    db, ctx = dc
    m = db.get(ChatMessage, message_id)
    if m is None or m.deleted_at is not None:
        raise NotFound("Message not found")
    if m.sender_id != ctx.user_id:
        raise Forbidden("Only the sender can delete it", code="NOT_SENDER")
    m.deleted_at = utcnow()
    db.commit()


# ---------------------------------------------------------------- delegation
class DelegationIn(BaseModel):
    to_user_id: uuid.UUID
    starts_at: datetime | None = None      # default: now
    ends_at: datetime
    note: str = Field("", max_length=500)


class DelegationOut(BaseModel):
    id: uuid.UUID
    from_user_id: uuid.UUID
    from_name: str = ""
    to_user_id: uuid.UUID
    to_name: str = ""
    starts_at: datetime
    ends_at: datetime
    note: str
    revoked_at: datetime | None
    active: bool = False


def _deleg_out(db, d: PermissionDelegation) -> DelegationOut:
    names = {u.id: u.full_name or u.username for u in db.scalars(select(User).where(
        User.id.in_([d.from_user_id, d.to_user_id])))}
    now = datetime.now(timezone.utc)
    return DelegationOut(id=d.id, from_user_id=d.from_user_id, from_name=names.get(d.from_user_id, ""),
                         to_user_id=d.to_user_id, to_name=names.get(d.to_user_id, ""), starts_at=d.starts_at,
                         ends_at=d.ends_at, note=d.note, revoked_at=d.revoked_at,
                         active=d.revoked_at is None and d.starts_at <= now < d.ends_at)


@router.get("/delegations", response_model=list[DelegationOut])
def list_delegations(dc=Depends(get_db_and_ctx)):
    """Mine (given and received); everyone's for an admin (users.manage)."""
    db, ctx = dc
    stmt = select(PermissionDelegation).order_by(PermissionDelegation.created_at.desc()).limit(200)
    if not ctx.can("users.manage"):
        stmt = stmt.where(or_(PermissionDelegation.from_user_id == ctx.user_id,
                              PermissionDelegation.to_user_id == ctx.user_id))
    return [_deleg_out(db, d) for d in db.scalars(stmt)]


@router.post("/delegations", response_model=DelegationOut, status_code=201)
def delegate(body: DelegationIn, dc=Depends(get_db_and_ctx)):
    """I give all my permissions to a colleague for a while (e.g. my leave)."""
    from app.modules.notifications.router import alert

    db, ctx = dc
    to = db.get(User, body.to_user_id)
    if to is None or to.deleted_at is not None or not to.is_active or to.id == ctx.user_id:
        raise ValidationFailed("Choose another active user", code="USER_UNKNOWN")
    starts = body.starts_at or datetime.now(timezone.utc)
    if starts.tzinfo is None or body.ends_at.tzinfo is None:
        raise ValidationFailed("Times need their time zone", code="BAD_TIME")
    if body.ends_at <= starts:
        raise ValidationFailed("The end is before the start", code="BAD_RANGE")
    if body.ends_at - starts > timedelta(days=366):
        raise ValidationFailed("At most a year", code="RANGE_TOO_LONG")
    d = PermissionDelegation(from_user_id=ctx.user_id, to_user_id=to.id, starts_at=starts, ends_at=body.ends_at,
                             note=body.note)
    db.add(d)
    db.flush()
    audit(db, d, "create")
    me = db.get(User, ctx.user_id)
    alert(db, ctx, "chat", None, f"{me.full_name or me.username} فوّضك بصلاحياته",
          f"من {starts:%Y-%m-%d %H:%M} لحد {body.ends_at:%Y-%m-%d %H:%M}" + (f" · {body.note}" if body.note else ""),
          "users?tab=delegations", users={to.id})
    db.commit()
    return _deleg_out(db, d)


@router.post("/delegations/{delegation_id}/revoke", response_model=DelegationOut)
def revoke(delegation_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    d = db.get(PermissionDelegation, delegation_id)
    if d is None:
        raise NotFound("Delegation not found")
    if ctx.user_id not in (d.from_user_id, d.to_user_id) and not ctx.can("users.manage"):
        raise Forbidden("Not yours", code="PERMISSION_DENIED")
    if d.revoked_at is not None:
        raise Conflict("Already stopped", code="ALREADY_REVOKED")
    before = snapshot(d)
    d.revoked_at = utcnow()
    audit(db, d, "update", before, note="إيقاف التفويض")
    db.commit()
    return _deleg_out(db, d)
