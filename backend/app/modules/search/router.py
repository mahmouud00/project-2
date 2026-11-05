"""البحث الشامل (Ctrl + K): one box that finds customers, surveys, quotations, work orders, invoices, purchase
orders, suppliers, employees and library items by number, code or name.

Each section is searched only when the caller may read it, within the branches they may read it in (the same
rules as its own list), and inside their company (RLS + the session's company filter). Personal data shown in the
results (customer / employee / supplier names and phones) is logged in pii_access_log like any list.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select

from app.core.pii import log_pii
from app.modules.crm.router import branch_scope
from app.tenancy.context import get_db_and_ctx

router = APIRouter(tags=["search"])


class Hit(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    path: str
    query: dict[str, str] = {}


class Group(BaseModel):
    kind: str
    label: str
    items: list[Hit]


class SearchOut(BaseModel):
    q: str
    groups: list[Group]


STATUS = {"draft": "مسودة", "sent": "اتبعت", "accepted": "مقبول", "rejected": "مرفوض", "expired": "منتهي",
          "open": "مفتوحة", "done": "خلصت", "cancelled": "ملغي", "issued": "صادرة", "ordered": "اتطلب",
          "received": "اتستلم", "active": "شغّال", "left": "ساب الشغل"}


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search", response_model=SearchOut)
def search(q: str = Query(min_length=1, max_length=100), limit: int = Query(6, ge=1, le=20), dc=Depends(get_db_and_ctx)):
    from app.modules.crm.models import Customer, SiteSurvey
    from app.modules.hr.models import Employee
    from app.modules.invoicing.models import Invoice
    from app.modules.library import service as lib
    from app.modules.library.models import Material, ProductModel, ProfileSystem
    from app.modules.production.models import WorkOrder
    from app.modules.purchasing.models import PurchaseOrder, Supplier
    from app.modules.sales.models import Quotation

    db, ctx = dc
    q = q.strip()
    like = _like(q)
    groups: list[Group] = []
    seen_customers: set = set()

    def add(kind: str, label: str, items: list[Hit]) -> None:
        if items:
            groups.append(Group(kind=kind, label=label, items=items))

    if ctx.can("customers.read"):
        stmt = select(Customer).where(Customer.deleted_at.is_(None), or_(
            Customer.name.ilike(like), Customer.code.ilike(like), Customer.phone.ilike(like))).order_by(Customer.name)
        rows = db.scalars(branch_scope(stmt, ctx, "customers.read", Customer.branch_id).limit(limit)).all()
        seen_customers |= {c.id for c in rows}
        add("customers", "العملاء", [Hit(id=str(c.id), title=c.name, subtitle=" · ".join(x for x in (c.code, c.phone) if x),
                                        path=f"customers/{c.id}") for c in rows])

    def documents(model, perm: str, kind: str, label: str, noun: str, path: str, *, numbered=True, status_attr="status"):
        if not ctx.can(perm):
            return
        stmt = (select(model, Customer.name).join(Customer, Customer.id == model.customer_id)
                .where(model.deleted_at.is_(None), or_(cast(model.number, String).ilike(like), Customer.name.ilike(like)))
                .order_by(model.created_at.desc()))
        rows = db.execute(branch_scope(stmt, ctx, perm, model.branch_id).limit(limit)).all()
        items = []
        for doc, customer in rows:
            seen_customers.add(doc.customer_id)
            state = STATUS.get(getattr(doc, status_attr, ""), "")
            items.append(Hit(id=str(doc.id), title=f"{noun} {doc.number or 'مسودة'}" if numbered else noun,
                             subtitle=" · ".join(x for x in (customer, state) if x), path=f"{path}/{doc.id}"))
        add(kind, label, items)

    documents(SiteSurvey, "surveys.read", "surveys", "المعاينات", "معاينة", "surveys")
    documents(Quotation, "quotes.read", "quotations", "عروض الأسعار", "عرض سعر", "quotations")
    documents(WorkOrder, "workorders.read", "work_orders", "أوامر التصنيع", "أمر تصنيع", "work-orders", status_attr="stage")
    documents(Invoice, "treasury.read", "invoices", "الفواتير", "فاتورة", "invoices")
    if seen_customers:
        log_pii(db, ctx, "customer", seen_customers, "search", ["name", "phone"])

    if ctx.can("purchasing.read"):
        stmt = (select(PurchaseOrder, Supplier.name).join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
                .where(PurchaseOrder.deleted_at.is_(None), or_(PurchaseOrder.number.ilike(like), Supplier.name.ilike(like)))
                .order_by(PurchaseOrder.created_at.desc()))
        rows = db.execute(branch_scope(stmt, ctx, "purchasing.read", PurchaseOrder.branch_id).limit(limit)).all()
        add("purchase_orders", "أوامر الشراء", [Hit(id=str(p.id), title=f"أمر شراء {p.number}",
                                                   subtitle=" · ".join(x for x in (name, STATUS.get(p.status, "")) if x),
                                                   path=f"purchasing/{p.id}") for p, name in rows])
        sup = db.scalars(select(Supplier).where(Supplier.deleted_at.is_(None), or_(
            Supplier.name.ilike(like), Supplier.code.ilike(like), Supplier.phone.ilike(like))).order_by(Supplier.name).limit(limit)).all()
        add("suppliers", "الموردين", [Hit(id=str(x.id), title=x.name, subtitle=" · ".join(v for v in (x.code, x.phone) if v),
                                         path="purchasing", query={"tab": "suppliers"}) for x in sup])

    if ctx.can("hr.read"):
        stmt = select(Employee).where(Employee.deleted_at.is_(None), or_(
            Employee.full_name.ilike(like), Employee.code.ilike(like), Employee.phone.ilike(like))).order_by(Employee.full_name)
        rows = db.scalars(branch_scope(stmt, ctx, "hr.read", Employee.branch_id).limit(limit)).all()
        if rows:
            log_pii(db, ctx, "employee", [e.id for e in rows], "search", ["full_name", "phone"])
        add("employees", "الموظفين", [Hit(id=str(e.id), title=e.full_name, subtitle=" · ".join(
            x for x in (e.code, STATUS.get(e.status, "")) if x), path=f"hr/{e.id}") for e in rows])

    if ctx.can("library.read") or ctx.can("platform.library.author"):
        visible = lib.visible_systems_stmt(db, ctx).subquery()
        names = {s.id: s.name for s in db.scalars(select(ProfileSystem).where(ProfileSystem.id.in_(select(visible.c.id))))}
        systems = [s for s in db.scalars(select(ProfileSystem).where(ProfileSystem.id.in_(select(visible.c.id)), or_(
            ProfileSystem.name.ilike(like), ProfileSystem.code.ilike(like))).order_by(ProfileSystem.name).limit(limit))]
        add("systems", "القطاعات", [Hit(id=str(s.id), title=s.name, subtitle=s.code, path=f"library/{s.id}") for s in systems])
        models = db.scalars(select(ProductModel).where(ProductModel.deleted_at.is_(None), ProductModel.system_id.in_(select(visible.c.id)),
                                                       or_(ProductModel.name.ilike(like), ProductModel.code.ilike(like)))
                            .order_by(ProductModel.code).limit(limit)).all()
        add("models", "النماذج", [Hit(id=str(m.id), title=m.name, subtitle=" · ".join(x for x in (m.code, names.get(m.system_id, "")) if x),
                                     path=f"library/{m.system_id}/models/{m.id}") for m in models])
        mats = db.scalars(select(Material).where(Material.deleted_at.is_(None), or_(
            Material.name.ilike(like), Material.code.ilike(like)), or_(Material.system_id.is_(None),
                                                                        Material.system_id.in_(select(visible.c.id))))
                          .order_by(Material.code).limit(limit)).all()
        add("materials", "الخامات", [Hit(id=str(m.id), title=m.name, subtitle=" · ".join(x for x in (m.code, names.get(m.system_id, "")) if x),
                                        path=f"library/{m.system_id}" if m.system_id else "library",
                                        query={"tab": "materials"} if m.system_id else {}) for m in mats])
    db.commit()
    return SearchOut(q=q, groups=groups)
