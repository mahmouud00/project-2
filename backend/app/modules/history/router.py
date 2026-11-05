"""سجل التغييرات لكل سجل: who changed what on one record, and when, from the audit log.

Anyone who may read the record may read its history (the record must be in their company, and in a branch where
they hold the read permission); the whole audit log stays for `audit.read`. Personal data was already masked
("***") when the change was logged. The record's own lines are included (a quotation's lines carry its prices).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, or_, select

from app.core.errors import NotFound, ValidationFailed
from app.core.pii import log_pii
from app.tenancy.context import get_db_and_ctx

router = APIRouter(tags=["history"])


class Entry(BaseModel):
    at: datetime
    user_id: uuid.UUID | None
    user_name: str | None
    entity: str
    entity_id: str
    action: str
    changes: dict
    note: str | None


def _kinds() -> dict:
    """kind -> (model, read permission, branch column name or None, (child table, child foreign key) or None)."""
    from app.modules.crm.models import Customer, SiteSurvey
    from app.modules.hr.models import Employee
    from app.modules.invoicing.models import Invoice
    from app.modules.library.models import Material, ProductModel, ProfileSystem
    from app.modules.production.models import WorkOrder
    from app.modules.purchasing.models import PurchaseOrder, Supplier
    from app.modules.sales.models import Quotation

    return {
        "quotations": (Quotation, "quotes.read", "branch_id", ("quotation_lines", "quotation_id")),
        "work_orders": (WorkOrder, "workorders.read", "branch_id", ("work_order_items", "work_order_id")),
        "site_surveys": (SiteSurvey, "surveys.read", "branch_id", ("survey_openings", "survey_id")),
        "invoices": (Invoice, "treasury.read", "branch_id", ("invoice_lines", "invoice_id")),
        "purchase_orders": (PurchaseOrder, "purchasing.read", "branch_id", ("purchase_order_lines", "purchase_order_id")),
        "customers": (Customer, "customers.read", "branch_id", None),
        "suppliers": (Supplier, "purchasing.read", None, None),
        "employees": (Employee, "hr.read", "branch_id", None),
        "product_models": (ProductModel, "library.read", None, ("model_test_cases", "model_id")),
        "profile_systems": (ProfileSystem, "library.read", None, ("system_constants", "system_id")),
        "materials": (Material, "library.read", None, None),
    }


@router.get("/history/{kind}/{record_id}", response_model=list[Entry])
def record_history(kind: str, record_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    from app.modules.org.models import AuditLog, User

    db, ctx = dc
    kinds = _kinds()
    if kind not in kinds:
        raise ValidationFailed("Unknown record kind", code="UNKNOWN_KIND", details=sorted(kinds))
    model, perm, branch_col, child = kinds[kind]
    if not (ctx.can(perm) or (perm == "library.read" and ctx.can("platform.library.author"))):
        ctx.require(perm)
    obj = db.get(model, record_id)                        # RLS: another company's record is simply not found
    if obj is None:
        raise NotFound("Record not found")
    if branch_col and getattr(obj, branch_col, None) is not None:
        allowed = ctx.branches_for(perm)
        if allowed is not None and getattr(obj, branch_col) not in allowed:
            raise NotFound("Record not found")

    rid = str(record_id)
    cond = and_(AuditLog.entity == kind, AuditLog.entity_id == rid)
    if child:
        table, fk = child
        # the record's lines now, and those made or removed before (their snapshot names the record): all their changes
        from app.db.base import Base

        lines = Base.metadata.tables[table]
        line_ids = {str(x) for x in db.scalars(select(lines.c.id).where(lines.c[fk] == record_id))}
        line_ids |= set(db.scalars(select(AuditLog.entity_id).where(
            AuditLog.entity == table, AuditLog.action.in_(("create", "delete")), AuditLog.changes[fk].astext == rid)))
        if line_ids:
            cond = or_(cond, and_(AuditLog.entity == table, AuditLog.entity_id.in_(line_ids)))
    rows = db.scalars(select(AuditLog).where(cond).order_by(AuditLog.at.desc()).limit(500)).all()
    users = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id})))}
    if users:
        log_pii(db, ctx, "user", users.keys(), "history", ["full_name"])
        db.commit()
    return [Entry(at=r.at, user_id=r.user_id, user_name=users.get(r.user_id), entity=r.entity, entity_id=r.entity_id,
                  action=r.action, changes=r.changes or {}, note=r.note) for r in rows]
