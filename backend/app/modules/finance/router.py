"""أصول الشركة، ربحيتها، ورأس مالها.

profit (per month) = sales (issued invoices, before tax) − purchases (value received from suppliers)
                     − salaries (paid payrolls, cost to the company) − expenses (money paid out to "other")
capital = opening capital (company settings) + assets still owned (at their value) + all profit to date
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import extract, func, select

from app.modules.deletions.router import deletable
from app.api.common import DeleteResult, Record, VersionedUpdate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.db.base import utcnow
from app.modules.crm.router import get_or_404
from app.modules.finance.models import ASSET_CATEGORIES, CompanyAsset
from app.modules.org.models import Branch
from app.tenancy.context import require

router = APIRouter(tags=["finance"])

CATEGORY = "^(" + "|".join(ASSET_CATEGORIES) + ")$"


class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field("other", pattern=CATEGORY)
    value: Decimal = Field(ge=0)
    purchase_date: date | None = None
    branch_id: uuid.UUID | None = None
    notes: str = ""


class AssetUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = Field(None, pattern=CATEGORY)
    value: Decimal | None = Field(None, ge=0)
    purchase_date: date | None = None
    branch_id: uuid.UUID | None = None
    status: str | None = Field(None, pattern="^(active|disposed)$")
    disposed_date: date | None = None
    notes: str | None = None


class AssetOut(Record):
    name: str
    category: str
    value: Decimal
    purchase_date: date | None
    branch_id: uuid.UUID | None
    status: str
    disposed_date: date | None
    notes: str


@router.get("/assets", response_model=list[AssetOut])
def list_assets(dc=Depends(require("finance.read"))):
    db, _ = dc
    return db.scalars(select(CompanyAsset).where(CompanyAsset.deleted_at.is_(None))
                      .order_by(CompanyAsset.status, CompanyAsset.category, CompanyAsset.name)).all()


@router.post("/assets", response_model=AssetOut, status_code=201)
def create_asset(body: AssetIn, dc=Depends(require("org.manage"))):
    db, _ = dc
    if body.branch_id:
        get_or_404(db, Branch, body.branch_id)
    a = CompanyAsset(**body.model_dump())
    db.add(a)
    db.flush()
    audit(db, a, "create")
    db.commit()
    return a


@router.patch("/assets/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: uuid.UUID, body: AssetUpdate, dc=Depends(require("org.manage"))):
    db, _ = dc
    a = get_or_404(db, CompanyAsset, asset_id)
    check_version(a, body.version)
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    if data.get("branch_id"):
        get_or_404(db, Branch, data["branch_id"])
    if data.get("status") == "disposed" and not data.get("disposed_date") and not a.disposed_date:
        data["disposed_date"] = date.today()
    if data.get("status") == "active":
        data["disposed_date"] = None
    before = snapshot(a)
    apply_changes(a, data)
    audit(db, a, "update", before)
    db.commit()
    return a


@deletable(router, "/assets/{asset_id}", "assets", ("الأصل", CompanyAsset, "name"))
def delete_asset(asset_id: uuid.UUID, dc=Depends(require("org.manage"))):
    """For an entry made by mistake. A sold or scrapped asset is marked "disposed" (keeps the history)."""
    db, _ = dc
    a = get_or_404(db, CompanyAsset, asset_id)
    before = snapshot(a)
    a.deleted_at = utcnow()
    audit(db, a, "delete", before)
    db.commit()
    return DeleteResult(result="deleted")


# ---------------------------------------------------------------- profit and capital
def _by_month(db, stmt) -> dict[str, Decimal]:
    return {f"{int(y):04d}-{int(m):02d}": Decimal(v or 0) for y, m, v in db.execute(stmt).all()}


def _figures(db, start: date | None, end: date) -> dict[str, dict[str, Decimal]]:
    """Each component per month (YYYY-MM) between start (or the beginning) and end."""
    from app.modules.hr.models import Payslip, PayrollRun
    from app.modules.invoicing.models import Invoice
    from app.modules.purchasing.models import PurchaseOrder
    from app.modules.treasury.models import CashTransaction

    def span(col):
        return (col >= start, col <= end) if start else (col <= end,)

    inv_date = Invoice.issue_date
    sales = _by_month(db, select(extract("year", inv_date), extract("month", inv_date),
                                 func.sum(Invoice.total - Invoice.tax_amount))
                      .where(Invoice.status == "issued", Invoice.deleted_at.is_(None), *span(inv_date))
                      .group_by(extract("year", inv_date), extract("month", inv_date)))
    po_date = PurchaseOrder.order_date
    purchases = _by_month(db, select(extract("year", po_date), extract("month", po_date),
                                     func.sum(PurchaseOrder.received_value))
                          .where(PurchaseOrder.deleted_at.is_(None), PurchaseOrder.received_value > 0, *span(po_date))
                          .group_by(extract("year", po_date), extract("month", po_date)))
    salaries: dict[str, Decimal] = {}
    for month, gross in db.execute(select(PayrollRun.month, func.sum(Payslip.gross))
                                   .join(Payslip, Payslip.run_id == PayrollRun.id)
                                   .where(PayrollRun.status == "paid", PayrollRun.deleted_at.is_(None))
                                   .group_by(PayrollRun.month)).all():
        if (not start or month >= start.strftime("%Y-%m")) and month <= end.strftime("%Y-%m"):
            salaries[month] = Decimal(gross or 0)
    tx_date = func.date(CashTransaction.at)
    expenses = _by_month(db, select(extract("year", CashTransaction.at), extract("month", CashTransaction.at),
                                    func.sum(CashTransaction.amount))
                         .where(CashTransaction.direction == "out", CashTransaction.party_type == "other",
                                CashTransaction.reversed.is_(False), CashTransaction.reverses_id.is_(None),
                                *span(tx_date))
                         .group_by(extract("year", CashTransaction.at), extract("month", CashTransaction.at)))
    return {"sales": sales, "purchases": purchases, "salaries": salaries, "expenses": expenses}


def _row(figs, months) -> dict[str, str]:
    parts = {k: sum((figs[k].get(m, Decimal(0)) for m in months), Decimal(0)) for k in figs}
    parts["profit"] = parts["sales"] - parts["purchases"] - parts["salaries"] - parts["expenses"]
    return {k: str(v.quantize(Decimal("0.01"))) for k, v in parts.items()}


@router.get("/finance/profit")
def profit(year: int | None = None, dc=Depends(require("finance.read"))):
    """ربحية الشركة: month by month for a year, and the year's total."""
    db, _ = dc
    year = year or date.today().year
    figs = _figures(db, date(year, 1, 1), date(year, 12, 31))
    months = [f"{year:04d}-{m:02d}" for m in range(1, 13)]
    return {"year": year, "months": [{"month": m, **_row(figs, [m])} for m in months],
            "total": _row(figs, months)}


def accumulated_profit(db, until: date | None = None) -> Decimal:
    until = until or date.today()
    figs = _figures(db, None, until)
    months = set().union(*(f.keys() for f in figs.values()))
    return Decimal(_row(figs, months)["profit"])


@router.get("/finance/capital")
def capital(dc=Depends(require("finance.read"))):
    """رأس المال = رأس المال الأساسي + الأصول + الأرباح المتراكمة."""
    from app.modules.org.settings import get_company_settings

    db, ctx = dc
    opening = get_company_settings(db, ctx.company_id).opening_capital
    assets = db.scalar(select(func.coalesce(func.sum(CompanyAsset.value), 0)).where(
        CompanyAsset.deleted_at.is_(None), CompanyAsset.status == "active")) or Decimal(0)
    by_cat = dict(db.execute(select(CompanyAsset.category, func.sum(CompanyAsset.value)).where(
        CompanyAsset.deleted_at.is_(None), CompanyAsset.status == "active").group_by(CompanyAsset.category)).all())
    profits = accumulated_profit(db)
    return {"opening_capital": str(opening), "assets": str(Decimal(assets)),
            "assets_by_category": {k: str(v) for k, v in by_cat.items()},
            "accumulated_profit": str(profits), "capital": str(opening + Decimal(assets) + profits)}
