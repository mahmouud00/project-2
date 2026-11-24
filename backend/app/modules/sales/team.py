"""The sales team: moving work between salespeople, and each salesperson's dashboard."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update

from app.core.audit import audit, snapshot
from app.core.errors import NotFound, ValidationFailed
from app.db.base import utcnow
from app.modules.sales import ownership
from app.tenancy.context import require

router = APIRouter(tags=["sales-team"])


class Person(BaseModel):
    id: uuid.UUID
    name: str


@router.get("/sales/people", response_model=list[Person])
def sales_people(dc=Depends(require("customers.read"))):
    """Whoever can make quotations: the salespeople (to move work to, or to open their dashboard)."""
    from app.modules.org.models import User
    from app.modules.notifications.router import recipients

    db, ctx = dc
    ids = recipients(db, "quotes.create", None)
    if ownership.mine_only(ctx):
        ids &= {ctx.user_id}
    users = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.full_name, User.username)).all()
    return [Person(id=u.id, name=u.full_name or u.username) for u in users]


class TransferIn(BaseModel):
    to_user_id: uuid.UUID


class TransferAllIn(TransferIn):
    from_user_id: uuid.UUID


def _target(db, user_id: uuid.UUID):
    from app.modules.org.models import User

    u = db.get(User, user_id)
    if u is None or not u.is_active:
        raise NotFound("User not found")
    return u


def _move(db, ctx, where, to: uuid.UUID) -> dict:
    """Give every matching customer, survey, quotation and invoice to `to`; how many of each moved."""
    moved = {}
    for model in ownership.models():
        res = db.execute(update(model).where(where(model)).values(owner_id=to, updated_at=utcnow(),
                                                                   version=model.version + 1))
        moved[model.__tablename__] = res.rowcount or 0
    return moved


@router.post("/customers/{customer_id}/transfer")
def transfer_customer(customer_id: uuid.UUID, body: TransferIn, dc=Depends(require("sales.transfer"))):
    """The customer and all his surveys, quotations and invoices go to another salesperson."""
    from app.modules.crm.models import Customer
    from app.modules.notifications.router import alert

    db, ctx = dc
    customer = db.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise NotFound("Customer not found")
    to = _target(db, body.to_user_id)
    before = snapshot(customer)
    old = customer.owner_id
    moved = _move(db, ctx, lambda m: (m.id == customer.id) if m is Customer else (m.customer_id == customer.id), to.id)
    db.refresh(customer)
    audit(db, customer, "update", before, note="نقل لموظف مبيعات تاني")
    alert(db, ctx, "sales", customer.branch_id, f"اتنقلك العميل {customer.name}", link=f"customers/{customer.id}",
          users={to.id})
    if old and old != to.id:
        alert(db, ctx, "sales", customer.branch_id, f"العميل {customer.name} اتنقل لموظف تاني", users={old})
    db.commit()
    return {"moved": moved}


@router.post("/sales/transfer")
def transfer_all(body: TransferAllIn, dc=Depends(require("sales.transfer"))):
    """All of one salesperson's work goes to another (he left, or changed job)."""
    from app.modules.notifications.router import alert

    db, ctx = dc
    if body.from_user_id == body.to_user_id:
        raise ValidationFailed("Same person", code="SAME_PERSON")
    to = _target(db, body.to_user_id)
    moved = _move(db, ctx, lambda m: m.owner_id == body.from_user_id, to.id)
    n = sum(moved.values())
    alert(db, ctx, "sales", None, f"اتنقلك شغل موظف مبيعات تاني ({moved.get('customers', 0)} عميل)", users={to.id})
    alert(db, ctx, "sales", None, "شغلك اتنقل لموظف مبيعات تاني", users={body.from_user_id})
    db.commit()
    return {"moved": moved, "total": n}
