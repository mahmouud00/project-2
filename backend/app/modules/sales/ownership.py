"""شغل كل موظف مبيعات: a customer, survey, quotation and invoice belong to whoever made it (`owner_id`). Without
«sales.all» a user sees only his own; the sales manager or the administrator moves work to another salesperson
(a customer with everything of it, or all of one person's work), and it leaves the first one's lists."""
from __future__ import annotations

import uuid

from app.core.errors import NotFound

ALL = "sales.all"


def mine_only(ctx) -> bool:
    return not ctx.can(ALL)


def scope(stmt, ctx, column):
    return stmt.where(column == ctx.user_id) if mine_only(ctx) else stmt


def check(ctx, obj) -> None:
    if obj is not None and mine_only(ctx) and getattr(obj, "owner_id", None) != ctx.user_id:
        raise NotFound(f"{type(obj).__name__} not found")


def owner_for(db, ctx, customer_id: uuid.UUID | None) -> uuid.UUID | None:
    """A document belongs to its customer's salesperson (a manager working on it keeps it with him)."""
    from app.modules.crm.models import Customer

    c = db.get(Customer, customer_id) if customer_id else None
    return (c.owner_id if c is not None and c.owner_id else None) or ctx.user_id


def models():
    from app.modules.crm.models import Customer, SiteSurvey
    from app.modules.invoicing.models import Invoice
    from app.modules.sales.models import Quotation
    return Customer, SiteSurvey, Quotation, Invoice
