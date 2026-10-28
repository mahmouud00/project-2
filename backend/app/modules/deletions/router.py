"""الحذف بعد ٣٠ يوم.

Pressing «حذف» never erases at once: it makes a deletion request with a 30-day countdown. The thing stays usable
and shows «جاري الحذف»; when the time is up it is erased by the scheduler. Whoever holds `delete.permanent` (the
administrator decides who) can erase it at once from the countdown, and the one who asked or that holder can take it
back. The same checks as the real deletion run when it is asked for (an issued invoice still cannot be deleted).

Money movements are not here: they are reversed, never deleted. Lines inside a document (a quotation line, a
constant of a system) are edits of that document and are deleted at once.

Erasing a library system, material or model that old work still points to hides it instead (the closed work keeps
its copy). The open work that uses it (a survey, a quotation not accepted yet, an order not in manufacturing yet, a
purchase not ordered yet, a model of the library) is told to replace it: its maker and the section's managers get a
notification when the deletion is asked for and again when it is done.
"""
from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import any_, literal, or_, select, text

from app.api.common import DeleteResult, ORMModel
from app.core.errors import AppError, Conflict, NotFound
from app.db.base import PLATFORM_COMPANY_ID, utcnow
from app.modules.deletions.models import DeletionRequest
from app.tenancy.context import RequestContext, get_db_and_ctx, require

log = logging.getLogger("mytech.deletions")
router = APIRouter(tags=["deletions"])

GRACE = timedelta(days=30)
PERMANENT = "delete.permanent"
DUE_LOCK = 7_300_002


@dataclass
class OpenWork:
    """A survey, quotation, order, purchase or model still using the thing being deleted."""
    company_id: uuid.UUID
    branch_id: uuid.UUID | None
    created_by: uuid.UUID | None
    permission: str              # who else hears about it: the section's managers
    category: str
    what: str                    # e.g. "عرض السعر QT-MAIN-2026-00012"
    link: str


@dataclass
class Deletable:
    kind: str
    perform: Callable
    param: str
    label: Callable
    open_work: Callable | None   # (system session, target id) -> list[OpenWork], read before erasing


REGISTRY: dict[str, Deletable] = {}


def deletable(router_: APIRouter, path: str, kind: str, label: tuple[str, type, str | None],
              open_work: Callable | None = None):
    """Turns a delete endpoint into «delete after 30 days». The decorated function stays the real deletion (run when
    the time is up or by «احذف دلوقتي»); the DELETE address now asks for it."""
    prefix, model, attr = label

    def describe(db, target_id) -> str:
        obj = db.get(model, target_id) if attr else None
        return f"{prefix} {getattr(obj, attr, '')}".strip() if obj is not None else prefix

    def wrap(fn):
        sig = inspect.signature(fn, eval_str=True)
        param = next(n for n in sig.parameters if n != "dc")
        REGISTRY[kind] = Deletable(kind, fn, param, describe, open_work)

        def ask(**kw):
            db, ctx = kw["dc"]
            return schedule(db, ctx, REGISTRY[kind], kw[param])

        ask.__signature__ = sig
        ask.__name__ = fn.__name__
        ask.__doc__ = "يطلب الحذف: بيتحذف نهائي بعد ٣٠ يوم، أو فورًا بصلاحية الحذف النهائي. " + (fn.__doc__ or "")
        router_.delete(path, response_model=DeleteResult)(ask)
        return fn
    return wrap


@contextmanager
def _no_commit(db):
    """Runs the real deletion as a check only: every commit becomes a flush inside a savepoint thrown away."""
    sp = db.begin_nested()
    db.commit = db.flush
    try:
        yield
    finally:
        del db.commit
        if sp.is_active:
            sp.rollback()


def full_context(company_id: uuid.UUID, user_id: uuid.UUID) -> RequestContext:
    """Rights used to carry out a deletion that was already allowed when it was asked for."""
    from app.auth.permissions import PERMISSIONS, PLATFORM_PERMISSIONS

    perms = set(PERMISSIONS) | (set(PLATFORM_PERMISSIONS) if company_id == PLATFORM_COMPANY_ID else set())
    return RequestContext(company_id, user_id, None, {None: perms})


def _result(req: DeletionRequest) -> DeleteResult:
    return DeleteResult(result="scheduled", request_id=req.id, due_at=req.due_at)


def schedule(db, ctx, spec: Deletable, target_id: uuid.UUID) -> DeleteResult:
    from app.modules.notifications.router import alert

    existing = db.scalar(select(DeletionRequest).where(DeletionRequest.kind == spec.kind,
                                                       DeletionRequest.target_id == target_id,
                                                       DeletionRequest.status == "pending"))
    if existing is not None:
        return _result(existing)
    with _no_commit(db):
        spec.perform(**{spec.param: target_id, "dc": (db, ctx)})
    label = spec.label(db, target_id)
    now = utcnow()
    req = DeletionRequest(kind=spec.kind, target_id=target_id, label=label[:200], requested_by=ctx.user_id,
                          requested_at=now, due_at=now + GRACE)
    db.add(req)
    db.flush()
    alert(db, ctx, "deletions", None, f"طلب حذف {label}", f"هيتحذف نهائي يوم {req.due_at:%Y-%m-%d}، إلا لو حد اتراجع.",
          "deletions")
    db.commit()
    _tell_open_work(spec, target_id, label, req.due_at)
    return _result(req)


def execute(db, ctx: RequestContext, req: DeletionRequest, by: uuid.UUID | None) -> DeletionRequest:
    """Erase it now (time is up, or «احذف دلوقتي»). If it can no longer be deleted the request fails with the
    reason and the one who asked is told."""
    from app.modules.notifications.models import Notification

    spec = REGISTRY.get(req.kind)
    req_id, label, requester = req.id, req.label, req.requested_by
    work = _open_work(spec, req.target_id) if spec else []
    status, note = "done", ""
    try:
        if spec is None:
            raise Conflict("Unknown kind", code="DELETE_KIND_UNKNOWN")
        r = spec.perform(**{spec.param: req.target_id, "dc": (db, ctx)})
        note = getattr(r, "result", "deleted")           # "deactivated": a cashbox with money history
    except NotFound:
        db.rollback()                       # already gone
    except AppError as e:
        db.rollback()
        status, note = "failed", e.code
    req = db.get(DeletionRequest, req_id)
    req.status, req.note, req.finished_at, req.finished_by = status, note, utcnow(), by
    if status == "failed":                  # told even when the hourly run acts as them
        db.add(Notification(user_id=requester, category="deletions", title=f"{label} ماتحذفش"[:200],
                            body=f"السبب: {note}", link="deletions"))
    db.commit()
    if status == "done":
        _notify(work, label, None)
    return req


# ---------------------------------------------------------------- open work told to replace a deleted thing
def _open_work(spec: Deletable | None, target_id) -> list[OpenWork]:
    if spec is None or spec.open_work is None:
        return []
    from app.db.session import system_session

    sdb = system_session()
    try:
        return spec.open_work(sdb, target_id)
    finally:
        sdb.close()


def _tell_open_work(spec: Deletable, target_id, label: str, due_at: datetime) -> None:
    _notify(_open_work(spec, target_id), label, due_at)


def _people(sdb, company_id, permission: str, branch_id) -> set[uuid.UUID]:
    from app.modules.org.models import Role, User, UserBranchRole

    stmt = (select(UserBranchRole.user_id).join(Role, Role.id == UserBranchRole.role_id)
            .join(User, User.id == UserBranchRole.user_id)
            .where(Role.company_id == company_id, literal(permission) == any_(Role.permissions), User.is_active.is_(True)))
    if branch_id is not None:
        stmt = stmt.where(or_(UserBranchRole.branch_id.is_(None), UserBranchRole.branch_id == branch_id))
    return set(sdb.scalars(stmt))


def _notify(work: list[OpenWork], label: str, due_at: datetime | None) -> None:
    """One notification per piece of open work for its maker and the section's managers (in that company)."""
    if not work:
        return
    from app.db.session import system_session
    from app.modules.notifications.models import Notification

    sdb = system_session()
    try:
        for w in work:
            users = _people(sdb, w.company_id, w.permission, w.branch_id) | ({w.created_by} if w.created_by else set())
            when = f"هيتحذف يوم {due_at:%Y-%m-%d}" if due_at else "اتحذف"
            for uid in users:
                sdb.add(Notification(company_id=w.company_id, user_id=uid, category=w.category,
                                     title=f"«{label}» {when}: غيّره في {w.what}"[:200],
                                     body="الحاجة دي اتطلب حذفها ولسه مستخدمة هنا. استبدلها بحاجة تانية.",
                                     link=w.link))
        sdb.commit()
    except Exception as e:                  # a notification must never undo a deletion
        sdb.rollback()
        log.error("open-work notifications failed: %s", type(e).__name__)
    finally:
        sdb.close()


def models_in_use(sdb, model_ids: list[uuid.UUID]) -> list[OpenWork]:
    from app.modules.crm.models import SiteSurvey, SurveyOpening
    from app.modules.production.models import WorkOrder, WorkOrderItem
    from app.modules.sales.models import Quotation, QuotationLine

    if not model_ids:
        return []
    out: dict[str, OpenWork] = {}
    for s in sdb.scalars(select(SiteSurvey).join(SurveyOpening, SurveyOpening.survey_id == SiteSurvey.id).where(
            or_(SurveyOpening.model_id.in_(model_ids), SurveyOpening.top_model_id.in_(model_ids)),
            SiteSurvey.deleted_at.is_(None), SiteSurvey.status == "open")):
        out[f"surveys/{s.id}"] = OpenWork(s.company_id, s.branch_id, s.created_by, "notify.sales", "sales",
                                          f"المعاينة {s.number}", f"surveys/{s.id}")
    for q in sdb.scalars(select(Quotation).join(QuotationLine, QuotationLine.quotation_id == Quotation.id).where(
            or_(QuotationLine.model_id.in_(model_ids), QuotationLine.top_model_id.in_(model_ids)),
            Quotation.deleted_at.is_(None), Quotation.status.in_(("draft", "sent")))):
        out[f"quotations/{q.id}"] = OpenWork(q.company_id, q.branch_id, q.created_by, "notify.sales", "sales",
                                             f"عرض السعر {q.number}", f"quotations/{q.id}")
    for w in sdb.scalars(select(WorkOrder).join(WorkOrderItem, WorkOrderItem.work_order_id == WorkOrder.id).where(
            WorkOrderItem.model_id.in_(model_ids), WorkOrder.deleted_at.is_(None),
            WorkOrder.stage.in_(("survey", "quotation", "approved")))):
        out[f"work-orders/{w.id}"] = OpenWork(w.company_id, w.branch_id, w.created_by, "notify.production",
                                              "production", f"أمر التصنيع {w.number}", f"work-orders/{w.id}")
    return list(out.values())


def materials_in_use(sdb, material_ids: list[uuid.UUID]) -> list[OpenWork]:
    from app.modules.library.models import Material, ProductModel
    from app.modules.library.service import referenced_codes
    from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderLine

    if not material_ids:
        return []
    materials = list(sdb.scalars(select(Material).where(Material.id.in_(material_ids))))
    out: dict[str, OpenWork] = {}
    for m in materials:
        models = select(ProductModel).where(ProductModel.deleted_at.is_(None), ProductModel.is_active,
                                            ProductModel.system_id.is_not(None))
        if m.company_id != PLATFORM_COMPANY_ID:                 # a company's own material: its models only
            models = models.where(ProductModel.company_id == m.company_id)
        for model in sdb.scalars(models):
            if m.code not in referenced_codes(model.definition):
                continue
            out[f"models/{model.id}"] = OpenWork(
                model.company_id, None, model.created_by,
                "platform.library.author" if model.company_id == PLATFORM_COMPANY_ID else "library.manage", "library",
                f"النموذج {model.code}", f"library/{model.system_id}/models/{model.id}")
    for po in sdb.scalars(select(PurchaseOrder).join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id ==
                                                     PurchaseOrder.id).where(
            PurchaseOrderLine.material_id.in_(material_ids), PurchaseOrder.deleted_at.is_(None),
            PurchaseOrder.status.in_(("draft", "approved", "rejected")))):
        out[f"purchase-orders/{po.id}"] = OpenWork(po.company_id, po.branch_id, po.created_by, "notify.accounts",
                                                   "accounts", f"أمر الشراء {po.number}", f"purchasing/{po.id}")
    return list(out.values())


# ---------------------------------------------------------------- endpoints
class DeletionOut(ORMModel):
    id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    label: str
    requested_by: uuid.UUID
    requested_by_name: str = ""
    requested_at: datetime
    due_at: datetime
    status: str
    finished_at: datetime | None
    note: str
    can_cancel: bool = False
    can_delete_now: bool = False


def _out(db, ctx, req: DeletionRequest) -> DeletionOut:
    from app.modules.org.models import User

    o = DeletionOut.model_validate(req)
    user = db.get(User, req.requested_by)
    o.requested_by_name = user.full_name or user.username if user else ""
    pending = req.status == "pending"
    o.can_delete_now = pending and ctx.can(PERMANENT)
    o.can_cancel = pending and (ctx.can(PERMANENT) or req.requested_by == ctx.user_id)
    return o


@router.get("/deletions", response_model=list[DeletionOut])
def list_deletions(status: str = "pending", dc=Depends(get_db_and_ctx)):
    """What is waiting to be deleted (with its countdown), or the finished ones (`status=done|cancelled|failed`)."""
    db, ctx = dc
    rows = db.scalars(select(DeletionRequest).where(DeletionRequest.status == status)
                      .order_by(DeletionRequest.due_at if status == "pending" else DeletionRequest.finished_at.desc())
                      .limit(500))
    return [_out(db, ctx, r) for r in rows]


def _pending(db, req_id) -> DeletionRequest:
    req = db.get(DeletionRequest, req_id)
    if req is None:
        raise NotFound("Deletion request not found")
    if req.status != "pending":
        raise Conflict("The deletion is not waiting any more", code="DELETION_NOT_PENDING")
    return req


@router.post("/deletions/{req_id}/now", response_model=DeletionOut)
def delete_now(req_id: uuid.UUID, dc=Depends(require(PERMANENT))):
    """حذف نهائي فورًا من غير ما يستنى الـ٣٠ يوم."""
    db, ctx = dc
    req = execute(db, full_context(ctx.company_id, ctx.user_id), _pending(db, req_id), ctx.user_id)
    if req.status == "failed":
        raise Conflict("It cannot be deleted any more", code=req.note or "DELETE_FAILED")
    return _out(db, ctx, req)


@router.post("/deletions/{req_id}/cancel", response_model=DeletionOut)
def cancel_deletion(req_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    """تراجع عن الحذف: the one who asked, or whoever holds the permanent delete permission."""
    from app.core.errors import Forbidden
    from app.modules.notifications.router import alert

    db, ctx = dc
    req = _pending(db, req_id)
    if req.requested_by != ctx.user_id and not ctx.can(PERMANENT):
        raise Forbidden("Only the one who asked or the permanent delete permission", code="PERMISSION_DENIED")
    req.status, req.finished_at, req.finished_by = "cancelled", utcnow(), ctx.user_id
    alert(db, ctx, "deletions", None, f"اتلغى حذف {req.label}", "", "deletions", users={req.requested_by})
    db.commit()
    return _out(db, ctx, req)


def run_due_deletions(now: datetime | None = None) -> int:
    """Hourly: erase what waited 30 days (every company). Runs as the one who asked."""
    from app.db.session import system_engine, system_session, tenant_session

    with system_engine().connect() as c:
        if not c.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": DUE_LOCK}).scalar():
            return 0
        try:
            sdb = system_session()
            try:
                due = sdb.execute(select(DeletionRequest.id, DeletionRequest.company_id, DeletionRequest.requested_by)
                                  .where(DeletionRequest.status == "pending",
                                         DeletionRequest.due_at <= (now or utcnow()))).all()
            finally:
                sdb.close()
            done = 0
            for rid, cid, uid in due:
                db = tenant_session(cid, uid)
                try:
                    req = db.get(DeletionRequest, rid)
                    if req is not None and req.status == "pending":
                        execute(db, full_context(cid, uid), req, None)
                        done += 1
                except Exception as e:
                    db.rollback()
                    log.error("deletion %s failed: %s", rid, type(e).__name__)
                finally:
                    db.close()
            return done
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": DUE_LOCK})
