"""الإشعارات: كل حدث مهم بيوصل للي ماسكين القسم (اللي عندهم صلاحية الإشعارات بتاعته في الفرع).

    accounts    بيعة أو أمر شراء مستني تأكيد الحسابات
    sales       أي تحديث على عميل: بياناته، معاينة، عرض سعر، تأكيد البيعة، تحصيل، فاتورة، صيانة
    production  بيعة اتأكدت (جاهزة للتصنيع) وكل نقل مرحلة في أمر التصنيع
    field       مهام الفنيين: اتعملت، الفني في الطريق، وصل، خلص؛ وطلبات الصيانة
    deletions   طلبات الحذف (لصاحب صلاحية الحذف النهائي)، وأي حاجة محذوفة لسه مستخدمة في شغل مفتوح

The program asks for new ones every few seconds and shows each as a Windows / Android notification.
The one who made the change is not notified about it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import any_, func, literal, or_, select, update

from app.api.common import ORMModel
from app.db.base import utcnow
from app.modules.notifications.models import Notification
from app.modules.org.models import Role, User, UserBranchRole
from app.tenancy.context import get_db_and_ctx

router = APIRouter(tags=["notifications"])

PERMISSION = {"accounts": "notify.accounts", "sales": "notify.sales", "production": "notify.production",
              "field": "notify.field", "deletions": "delete.permanent"}


def recipients(db, permission: str, branch_id: uuid.UUID | None) -> set[uuid.UUID]:
    """Active users holding `permission` in that branch (or in every branch)."""
    stmt = (select(UserBranchRole.user_id).join(Role, Role.id == UserBranchRole.role_id)
            .join(User, User.id == UserBranchRole.user_id)
            .where(literal(permission) == any_(Role.permissions), User.is_active.is_(True)))
    if branch_id is not None:
        stmt = stmt.where(or_(UserBranchRole.branch_id.is_(None), UserBranchRole.branch_id == branch_id))
    return set(db.scalars(stmt))


def alert(db, ctx, category: str, branch_id: uuid.UUID | None, title: str, body: str = "", link: str = "",
          users: set[uuid.UUID] | None = None) -> None:
    """Notify the section's people (or the given users). Not committed: it goes with the change itself."""
    targets = set(users) if users is not None else recipients(db, PERMISSION[category], branch_id)
    targets.discard(getattr(ctx, "user_id", None))
    for uid in targets:
        db.add(Notification(user_id=uid, category=category, title=title[:200], body=body, link=link))


class NotificationOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    category: str
    title: str
    body: str
    link: str
    read_at: datetime | None


class Inbox(BaseModel):
    unread: int
    items: list[NotificationOut]


@router.get("/notifications", response_model=Inbox)
def my_notifications(after: datetime | None = None, limit: int = 30, dc=Depends(get_db_and_ctx)):
    """My latest notifications (or only those after a time, for polling) and how many are unread."""
    db, ctx = dc
    mine = select(Notification).where(Notification.user_id == ctx.user_id)
    if after:
        mine = mine.where(Notification.created_at > after)
    items = db.scalars(mine.order_by(Notification.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    unread = db.scalar(select(func.count()).where(Notification.user_id == ctx.user_id,
                                                  Notification.read_at.is_(None))) or 0
    return Inbox(unread=unread, items=[NotificationOut.model_validate(n) for n in items])


@router.post("/notifications/{nid}/read", response_model=Inbox)
def read_one(nid: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    db.execute(update(Notification).where(Notification.id == nid, Notification.user_id == ctx.user_id,
                                          Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return my_notifications(None, 30, dc)


@router.post("/notifications/read-all", response_model=Inbox)
def read_all(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    db.execute(update(Notification).where(Notification.user_id == ctx.user_id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()
    return my_notifications(None, 30, dc)


def purge_old_notifications(db, days: int = 90) -> int:
    """Daily: notifications older than `days` are deleted (they are reminders, not records)."""
    res = db.execute(Notification.__table__.delete().where(Notification.created_at < utcnow() - timedelta(days=days)))
    return res.rowcount or 0


def customer_name(db, customer_id) -> str:
    from app.modules.crm.models import Customer

    c = db.get(Customer, customer_id) if customer_id else None
    return c.name if c else ""
