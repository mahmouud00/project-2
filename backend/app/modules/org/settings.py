"""Company-level settings (stored in companies.settings JSON).

These are business / machine settings the company edits (tax, currency, saw
kerf...), not deduction formulas. Defaults apply until the company sets them.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.audit import audit, snapshot
from app.modules.org.models import Company
from app.tenancy.context import get_db_and_ctx, require


class CompanySettings(BaseModel):
    currency: str = "EGP"
    default_tax_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    quote_validity_days: int = Field(15, ge=1)
    quote_waste_pct: Decimal = Field(Decimal(0), ge=0, le=100, description="waste added to profile cost in quotes")
    deposit_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    saw_kerf_mm: Decimal = Field(Decimal(0), ge=0)
    bar_trim_mm: Decimal = Field(Decimal(0), ge=0, description="trimmed at each end of a bar")
    min_reusable_offcut_mm: Decimal = Field(Decimal(0), ge=0)
    quote_terms: str = ""


def get_company_settings(db, company_id) -> CompanySettings:
    company = db.get(Company, company_id)
    return CompanySettings(**(company.settings or {})) if company else CompanySettings()


router = APIRouter(tags=["org"])


@router.get("/company", response_model=dict)
def get_company(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    c = db.get(Company, ctx.company_id)
    return {"id": str(c.id), "code": c.code, "name": c.name, "version": c.version,
            "settings": get_company_settings(db, ctx.company_id).model_dump(mode="json")}


class CompanyUpdate(BaseModel):
    version: int
    name: str | None = None
    settings: CompanySettings | None = None


@router.patch("/company", response_model=dict)
def update_company(body: CompanyUpdate, dc=Depends(require("org.manage"))):
    from app.core.audit import check_version

    db, ctx = dc
    c = db.get(Company, ctx.company_id)
    check_version(c, body.version)
    before = snapshot(c)
    if body.name:
        c.name = body.name
    if body.settings:
        c.settings = body.settings.model_dump(mode="json")
    audit(db, c, "update", before)
    db.commit()
    return get_company(dc)
