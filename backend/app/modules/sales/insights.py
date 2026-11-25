"""داش بورد موظف المبيعات: everything about one salesperson's work for a period (customers, surveys, quotations,
sales, invoices, collections, what needs following up) and a monthly history; the same report feeds the n8n bot.
A salesperson sees his own; whoever has «sales.all» opens anyone's, and the team table."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.core.errors import Forbidden
from app.modules.sales import ownership
from app.modules.sales.pricing import money
from app.tenancy.context import require

router = APIRouter(tags=["sales-team"])
TZ = "Africa/Cairo"


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TZ)
    return datetime.combine(start, time.min, tzinfo=tz), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)


def period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    from app.modules.hr.policy import local_now
    today = local_now().date()
    return date_from or today.replace(day=1), date_to or today


def _d(x) -> Decimal:
    return money(Decimal(x or 0))


def report(db, user_id: uuid.UUID, start: date, end: date) -> dict:
    from app.modules.crm.models import Customer, SiteSurvey
    from app.modules.invoicing.models import Collection, Invoice
    from app.modules.org.models import User
    from app.modules.sales.models import Quotation

    lo, hi = _bounds(start, end)
    user = db.get(User, user_id)
    in_period = lambda col: (col >= lo, col < hi)

    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    live = lambda m: (m.owner_id == user_id, m.deleted_at.is_(None))
    customers = {"total": count(Customer, *live(Customer)),
                 "new": count(Customer, *live(Customer), *in_period(Customer.created_at)),
                 "by_contact_method": {k or "—": n for k, n in db.execute(
                     select(Customer.contact_method, func.count()).where(*live(Customer), *in_period(Customer.created_at))
                     .group_by(Customer.contact_method)).all()}}
    surveys = {"made": count(SiteSurvey, *live(SiteSurvey), *in_period(SiteSurvey.created_at)),
               "waiting_manager": count(SiteSurvey, *live(SiteSurvey), SiteSurvey.approval_status == "pending")}

    q_rows = db.execute(select(Quotation.status, func.count(), func.coalesce(func.sum(Quotation.total), 0))
                        .where(*live(Quotation), *in_period(Quotation.created_at))
                        .group_by(Quotation.status)).all()
    by_status = {s: {"count": n, "value": str(_d(v))} for s, n, v in q_rows}
    made = sum(n for _, n, _ in q_rows)
    accepted = by_status.get("accepted", {"count": 0, "value": "0.00"})
    decided = accepted["count"] + by_status.get("rejected", {"count": 0})["count"]
    stale = db.scalars(select(Quotation).where(*live(Quotation), Quotation.status == "sent",
                                               Quotation.updated_at < datetime.now(lo.tzinfo) - timedelta(days=7))
                       .order_by(Quotation.updated_at).limit(10)).all()
    quotations = {
        "made": made, "by_status": by_status,
        "value_made": str(_d(sum((Decimal(v["value"]) for v in by_status.values()), Decimal(0)))),
        "accepted_count": accepted["count"], "accepted_value": accepted["value"],
        "conversion_pct": str(Decimal(accepted["count"] * 100 / decided).quantize(Decimal("0.1")) if decided else Decimal(0)),
        "average_value": str(_d(sum((Decimal(v["value"]) for v in by_status.values()), Decimal(0)) / made) if made else "0.00"),
        "waiting_manager": count(Quotation, *live(Quotation), Quotation.approval_status == "pending"),
        "discount_requests": count(Quotation, *live(Quotation), Quotation.discount_requested_at.is_not(None)),
        "discount_given": str(_d(db.scalar(select(func.coalesce(func.sum(Quotation.discount_amount), 0)).where(
            *live(Quotation), Quotation.status == "accepted", *in_period(Quotation.created_at))))),
        "to_follow_up": [{"id": str(q.id), "number": q.number, "total": str(q.total),
                          "days": (datetime.now(lo.tzinfo) - q.updated_at).days} for q in stale],
    }

    issued = (Invoice.owner_id == user_id, Invoice.deleted_at.is_(None), Invoice.status == "issued")
    inv_period = db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0))
                            .where(*issued, Invoice.issue_date >= start, Invoice.issue_date <= end)).one()
    from app.modules.invoicing.router import invoice_out
    open_balance = sum((invoice_out(db, i).balance for i in db.scalars(select(Invoice).where(*issued))), Decimal(0))
    invoices = {"issued": inv_period[0], "sales_value": str(_d(inv_period[1])), "open_balance": str(_d(open_balance))}

    mine = (Collection.owner_id == user_id,)
    conf = db.scalar(select(func.coalesce(func.sum(Collection.amount), 0)).where(
        *mine, Collection.status == "confirmed", Collection.decided_at >= lo, Collection.decided_at < hi))
    pend = db.execute(select(func.count(), func.coalesce(func.sum(Collection.amount), 0))
                      .where(*mine, Collection.status == "pending")).one()
    rejected = count(Collection, *mine, Collection.status == "rejected", *in_period(Collection.created_at))
    collections = {"confirmed": str(_d(conf)), "pending_count": pend[0], "pending_amount": str(_d(pend[1])),
                   "rejected": rejected,
                   "collection_pct": str((_d(conf) * 100 / _d(inv_period[1])).quantize(Decimal("0.1")))
                   if _d(inv_period[1]) else "0.0"}

    top = db.execute(select(Customer.name, func.sum(Invoice.total)).join(Customer, Customer.id == Invoice.customer_id)
                     .where(*issued, Invoice.issue_date >= start, Invoice.issue_date <= end)
                     .group_by(Customer.name).order_by(func.sum(Invoice.total).desc()).limit(5)).all()

    months = []
    first = start.replace(day=1)
    for k in range(5, -1, -1):
        y, m = first.year, first.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        m_start = date(y, m, 1)
        m_end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        a, b = _bounds(m_start, m_end)
        months.append({"month": f"{y}-{m:02d}",
                       "sales": str(_d(db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(
                           *issued, Invoice.issue_date >= m_start, Invoice.issue_date <= m_end)))),
                       "collected": str(_d(db.scalar(select(func.coalesce(func.sum(Collection.amount), 0)).where(
                           *mine, Collection.status == "confirmed", Collection.decided_at >= a, Collection.decided_at < b)))),
                       "quotations": count(Quotation, *live(Quotation), Quotation.created_at >= a, Quotation.created_at < b)})
    return {"user_id": str(user_id), "name": (user.full_name or user.username) if user else "",
            "from": start.isoformat(), "to": end.isoformat(), "customers": customers, "surveys": surveys,
            "quotations": quotations, "invoices": invoices, "collections": collections,
            "top_customers": [{"name": n, "sales": str(_d(v))} for n, v in top], "months": months}


@router.get("/sales/dashboard")
def dashboard(user_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
              dc=Depends(require("quotes.read"))):
    """One salesperson's work (his own; another's only with «sales.all»)."""
    db, ctx = dc
    who = user_id or ctx.user_id
    if who != ctx.user_id and ownership.mine_only(ctx):
        raise Forbidden("Only your own dashboard", code="FORBIDDEN")
    start, end = period(date_from, date_to)
    return report(db, who, start, end)


@router.get("/sales/team")
def team(date_from: date | None = None, date_to: date | None = None, dc=Depends(require("sales.all"))):
    """The sales manager's table: every salesperson side by side for the period."""
    from app.modules.notifications.router import recipients
    from app.modules.org.models import User

    db, ctx = dc
    start, end = period(date_from, date_to)
    rows = []
    for u in db.scalars(select(User).where(User.id.in_(recipients(db, "quotes.create", None)))):
        r = report(db, u.id, start, end)
        rows.append({"user_id": str(u.id), "name": r["name"], "customers_new": r["customers"]["new"],
                     "quotations": r["quotations"]["made"], "accepted": r["quotations"]["accepted_count"],
                     "conversion_pct": r["quotations"]["conversion_pct"], "sales": r["invoices"]["sales_value"],
                     "collected": r["collections"]["confirmed"], "open_balance": r["invoices"]["open_balance"]})
    rows.sort(key=lambda x: Decimal(x["sales"]), reverse=True)
    return {"from": start.isoformat(), "to": end.isoformat(), "people": rows}
