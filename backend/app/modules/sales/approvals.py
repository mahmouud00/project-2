"""تأكيد مدير المبيعات on a survey (before a quotation is made from it) and on a quotation (before it reaches the
customer). The salesperson sends it to the sales manager (a notification); the manager confirms it and the salesperson
is told. A change afterwards needs a new confirmation. Whoever may confirm does not wait for himself."""
from __future__ import annotations

from app.core.audit import audit, snapshot
from app.core.errors import Conflict
from app.db.base import utcnow

WORDS = {"surveys": ("المعاينة", "surveys.approve", "surveys"), "quotations": ("عرض السعر", "quotes.approve", "quotations")}


def _word(obj) -> tuple[str, str, str]:
    return WORDS[obj.__tablename__ if obj.__tablename__ != "site_surveys" else "surveys"]


def request(db, ctx, obj) -> None:
    from app.modules.notifications.router import alert, customer_name, recipients

    what, perm, link = _word(obj)
    if obj.approval_status == "approved":
        raise Conflict("Already confirmed", code="ALREADY_APPROVED")
    before = snapshot(obj)
    obj.approval_status, obj.approval_requested_at = "pending", utcnow()
    audit(db, obj, "update", before, note="اتبعت لمدير المبيعات للتأكيد")
    alert(db, ctx, "sales", obj.branch_id, f"{what} {obj.number} مستني تأكيدك", customer_name(db, obj.customer_id),
          f"{link}/{obj.id}", users=recipients(db, perm, obj.branch_id))


def approve(db, ctx, obj) -> None:
    from app.modules.notifications.router import alert, customer_name

    what, perm, link = _word(obj)
    ctx.require(perm, obj.branch_id)
    before = snapshot(obj)
    obj.approval_status, obj.approved_at, obj.approved_by = "approved", utcnow(), ctx.user_id
    audit(db, obj, "update", before, note="تأكيد مدير المبيعات")
    if obj.created_by:
        alert(db, ctx, "sales", obj.branch_id, f"مدير المبيعات أكد {what} {obj.number}",
              customer_name(db, obj.customer_id), f"{link}/{obj.id}", users={obj.created_by})


def changed(obj) -> None:
    """Something changed after the confirmation (or while waiting): confirm again."""
    if obj.approval_status != "none":
        obj.approval_status, obj.approval_requested_at, obj.approved_at, obj.approved_by = "none", None, None, None


def ensure(db, ctx, obj) -> None:
    """Before the next step: confirmed, or confirmed now by whoever may confirm."""
    if obj.approval_status == "approved":
        return
    what, perm, _ = _word(obj)
    if ctx.can(perm, obj.branch_id):
        obj.approval_status, obj.approved_at, obj.approved_by = "approved", utcnow(), ctx.user_id
        return
    raise Conflict(f"The sales manager must confirm the {obj.__tablename__} first", code="NEEDS_MANAGER_APPROVAL",
                   details={"what": what, "status": obj.approval_status})
