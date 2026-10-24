"""Data-subject rights (Law 151/2020): export and erasure, plus the access log.

Erasure = anonymisation: identifying fields are wiped, but quotations, work
orders, payments and stock records are kept (financial/legal retention),
now pointing at an anonymous customer.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import ORMModel, Page, PageParams, paginate
from app.core.audit import _jsonable, audit, snapshot
from app.core.errors import NotFound, ValidationFailed
from app.core.pii import log_pii
from app.modules.crm.models import Customer, SiteSurvey, SurveyOpening
from app.modules.org.models import PiiAccessLog, User
from app.modules.production.models import WorkOrder
from app.modules.purchasing.models import Supplier
from app.modules.sales.models import Quotation
from app.modules.treasury.models import CashTransaction
from app.tenancy.context import require

router = APIRouter(prefix="/privacy", tags=["privacy"])

SUBJECTS = {"customer": Customer, "user": User, "supplier": Supplier}


def _plain(obj) -> dict:
    out = {}
    from sqlalchemy import inspect
    for attr in inspect(obj).mapper.column_attrs:
        if attr.key in ("password_hash",):
            continue
        out[attr.key] = _jsonable(getattr(obj, attr.key))
    return out


def _subject(db, subject_type: str, subject_id: uuid.UUID):
    model = SUBJECTS.get(subject_type)
    if model is None:
        raise ValidationFailed("Unknown subject type", code="SUBJECT_TYPE")
    obj = db.get(model, subject_id)
    if obj is None:
        raise NotFound("Subject not found")
    return obj


@router.get("/subjects/{subject_type}/{subject_id}/export")
def export_subject(subject_type: str, subject_id: uuid.UUID, dc=Depends(require("privacy.manage"))):
    db, ctx = dc
    obj = _subject(db, subject_type, subject_id)
    data = {"subject_type": subject_type, "exported_at": datetime.now().astimezone().isoformat(),
            "personal_data": _plain(obj)}
    if subject_type == "customer":
        surveys = db.scalars(select(SiteSurvey).where(SiteSurvey.customer_id == obj.id)).all()
        data["surveys"] = [{**_plain(s), "openings": [_plain(o) for o in db.scalars(
            select(SurveyOpening).where(SurveyOpening.survey_id == s.id))]} for s in surveys]
        data["quotations"] = [{k: v for k, v in _plain(q).items()} for q in
                              db.scalars(select(Quotation).where(Quotation.customer_id == obj.id))]
        data["work_orders"] = [{k: v for k, v in _plain(w).items() if k != "outputs"} for w in
                               db.scalars(select(WorkOrder).where(WorkOrder.customer_id == obj.id))]
        data["payments"] = [_plain(t) for t in db.scalars(select(CashTransaction).where(
            CashTransaction.party_type == "customer", CashTransaction.party_id == obj.id))]
    log_pii(db, ctx, subject_type, [obj.id], "export", list(obj.__pii__))
    db.commit()
    return data


class EraseIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/subjects/{subject_type}/{subject_id}/erase")
def erase_subject(subject_type: str, subject_id: uuid.UUID, body: EraseIn, dc=Depends(require("privacy.manage"))):
    db, ctx = dc
    obj = _subject(db, subject_type, subject_id)
    if subject_type == "user" and obj.id == ctx.user_id:
        raise ValidationFailed("Cannot erase yourself", code="SELF_ERASE")
    before = snapshot(obj)
    fields = [f for f in obj.__pii__ if getattr(obj, f) not in (None, "")]
    for f in obj.__pii__:
        column = getattr(type(obj), f).property.columns[0]
        setattr(obj, f, None if column.nullable else "")
    if subject_type == "customer":
        obj.name = f"عميل محذوف {obj.code}"
        obj.anonymized = True
        for s in db.scalars(select(SiteSurvey).where(SiteSurvey.customer_id == obj.id)):
            s.address = None
    elif subject_type == "user":
        obj.full_name = "مستخدم محذوف"
        obj.is_active = False
    elif subject_type == "supplier":
        obj.contact_name = None
    audit(db, obj, "update", before, note=f"personal data erased: {body.reason}")
    log_pii(db, ctx, subject_type, [obj.id], "erase", fields)
    db.commit()
    return {"status": "erased", "fields": sorted(fields)}


class AccessLogOut(ORMModel):
    id: uuid.UUID
    at: datetime
    user_id: uuid.UUID | None
    device_id: uuid.UUID | None
    ip: str | None
    subject_type: str
    subject_id: str
    action: str
    fields: list[str]


@router.get("/access-log", response_model=Page[AccessLogOut])
def access_log(subject_id: str | None = None, user_id: uuid.UUID | None = None, params: PageParams = Depends(),
               dc=Depends(require("privacy.manage"))):
    db, _ = dc
    stmt = select(PiiAccessLog).order_by(PiiAccessLog.at.desc())
    if subject_id:
        stmt = stmt.where(PiiAccessLog.subject_id == subject_id)
    if user_id:
        stmt = stmt.where(PiiAccessLog.user_id == user_id)
    return paginate(db, stmt, params, AccessLogOut)
