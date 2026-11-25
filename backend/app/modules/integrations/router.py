"""الربط مع n8n (أو أي برنامج تاني): a company key («مفتاح ربط») in the header `X-API-Key` reads the salespeople and
each one's report, and sends a salesperson tips (a notification). Made and revoked by the administrator.
See docs/N8N.md and tools/n8n/sales-coach.json."""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import Record
from app.core.audit import audit
from app.core.errors import NotFound, Unauthorized
from app.db.base import utcnow
from app.db.session import system_session, tenant_session
from app.modules.integrations.models import IntegrationKey
from app.modules.sharing.router import token_hash
from app.tenancy.context import require

router = APIRouter(tags=["integrations"])
PREFIX = "mtk_"


class KeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class KeyOut(Record):
    name: str
    prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    key: str | None = None             # only in the answer that made it


@router.get("/integrations/keys", response_model=list[KeyOut])
def list_keys(dc=Depends(require("integrations.manage"))):
    db, _ = dc
    return db.scalars(select(IntegrationKey).order_by(IntegrationKey.created_at.desc())).all()


@router.post("/integrations/keys", response_model=KeyOut, status_code=201)
def make_key(body: KeyIn, dc=Depends(require("integrations.manage"))):
    db, ctx = dc
    key = PREFIX + secrets.token_urlsafe(32)
    k = IntegrationKey(name=body.name, key_hash=token_hash(key), prefix=key[:10], acting_user_id=ctx.user_id)
    db.add(k)
    db.flush()
    audit(db, k, "create")
    db.commit()
    out = KeyOut.model_validate(k)
    out.key = key
    return out


@router.post("/integrations/keys/{key_id}/revoke", response_model=KeyOut)
def revoke_key(key_id: uuid.UUID, dc=Depends(require("integrations.manage"))):
    db, _ = dc
    k = db.get(IntegrationKey, key_id)
    if k is None:
        raise NotFound("Key not found")
    k.revoked_at = k.revoked_at or utcnow()
    db.commit()
    return k


def keyed(x_api_key: str = Header("")):
    """(tenant session, context) of the company whose live key this is; the key may read sales and send tips."""
    from app.modules.deletions.router import full_context

    if not x_api_key.startswith(PREFIX) or len(x_api_key) > 100:
        raise Unauthorized("Integration key required", code="INTEGRATION_KEY")
    with system_session() as sdb:
        k = sdb.scalar(select(IntegrationKey).where(IntegrationKey.key_hash == token_hash(x_api_key)))
        if k is None or k.revoked_at is not None:
            raise Unauthorized("Integration key not valid", code="INTEGRATION_KEY")
        k.last_used_at = utcnow()
        sdb.commit()
        company_id, user_id = k.company_id, k.acting_user_id
    db = tenant_session(company_id, None)
    try:
        yield db, full_context(company_id, user_id or uuid.UUID(int=0))
    finally:
        db.close()


@router.get("/integrations/sales/people")
def bot_people(dc=Depends(keyed)):
    from app.modules.notifications.router import recipients
    from app.modules.org.models import User

    db, _ = dc
    users = db.scalars(select(User).where(User.id.in_(recipients(db, "quotes.create", None)))).all()
    return [{"id": str(u.id), "name": u.full_name or u.username} for u in users]


@router.get("/integrations/sales/report")
def bot_report(user_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None, dc=Depends(keyed)):
    """The same report as the salesperson's dashboard (no personal data of customers beyond their names)."""
    from app.modules.sales.insights import period, report

    db, _ = dc
    start, end = period(date_from, date_to)
    return report(db, user_id, start, end)


class TipIn(BaseModel):
    user_id: uuid.UUID
    title: str = Field(min_length=2, max_length=200)
    body: str = Field("", max_length=4000)


@router.post("/integrations/sales/tips", status_code=201)
def bot_tip(body: TipIn, dc=Depends(keyed)):
    """The bot's advice reaches the salesperson as a notification «نصيحة»."""
    from app.modules.notifications.models import Notification
    from app.modules.org.models import User

    db, _ = dc
    if db.get(User, body.user_id) is None:
        raise NotFound("User not found")
    db.add(Notification(user_id=body.user_id, category="sales", title=("نصيحة: " + body.title)[:200], body=body.body,
                        link="sales-dashboard"))
    db.commit()
    return {"sent": True}
