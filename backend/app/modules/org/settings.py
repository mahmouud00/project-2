"""Company-level settings (stored in companies.settings JSON).

These are business / machine settings the company edits (tax, currency, saw
kerf...), not deduction formulas. Defaults apply until the company sets them.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

import uuid

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field

from app.core.audit import audit, snapshot
from app.modules.org.models import Company
from app.tenancy.context import get_db_and_ctx, require


class CompanySettings(BaseModel):
    # Branding shown on every screen and on printed quotations / invoices
    display_name: str = ""          # shown instead of the legal company name when set
    phone: str = ""
    phone2: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    tax_number: str = ""            # الرقم الضريبي
    commercial_register: str = ""   # السجل التجاري
    invoice_footer: str = ""
    accent_color: str = Field("", pattern=r"^(#[0-9A-Fa-f]{6})?$")
    logo_media_id: str | None = None  # set through POST /company/logo

    currency: str = "EGP"
    default_tax_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    quote_validity_days: int = Field(15, ge=1)
    quote_waste_pct: Decimal = Field(Decimal(0), ge=0, le=100, description="waste added to profile cost in quotes")
    deposit_pct: Decimal = Field(Decimal(0), ge=0, le=100)
    min_billed_area_m2: Decimal = Field(Decimal(1), ge=0, description="price per m² bills at least this area per unit")
    saw_kerf_mm: Decimal = Field(Decimal(0), ge=0)
    bar_trim_mm: Decimal = Field(Decimal(0), ge=0, description="trimmed at each end of a bar")
    min_reusable_offcut_mm: Decimal = Field(Decimal(0), ge=0)
    quote_terms: str = ""
    # Unit the desktop app shows and accepts lengths in. The API always speaks millimetres.
    length_unit: Literal["cm", "mm"] = "cm"


def get_company_settings(db, company_id) -> CompanySettings:
    company = db.get(Company, company_id)
    return CompanySettings(**(company.settings or {})) if company else CompanySettings()


router = APIRouter(tags=["org"])


def branding(db, company) -> dict:
    s = get_company_settings(db, company.id)
    return {"company_code": company.code, "name": s.display_name or company.name, "legal_name": company.name,
            "phone": s.phone, "phone2": s.phone2, "email": s.email, "website": s.website, "address": s.address,
            "tax_number": s.tax_number, "commercial_register": s.commercial_register,
            "invoice_footer": s.invoice_footer, "accent_color": s.accent_color or None,
            "has_logo": bool(s.logo_media_id), "logo_media_id": s.logo_media_id}


@router.post("/company/logo", response_model=dict)
async def upload_logo(file: UploadFile, dc=Depends(require("org.manage"))):
    """The company's own logo: shown in the app header and on every printed document."""
    from app.modules.library.router import read_image

    db, ctx = dc
    media = await read_image(db, file)
    company = db.get(Company, ctx.company_id)
    before = snapshot(company)
    settings = dict(company.settings or {})
    settings["logo_media_id"] = str(media.id)
    company.settings = settings
    audit(db, company, "update", before, note="logo changed")
    db.commit()
    return branding(db, company)


@router.get("/company/logo")
def get_logo(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    return _logo_response(db, db.get(Company, ctx.company_id))


def _logo_response(db, company):
    from fastapi.responses import FileResponse

    from app.core.errors import NotFound
    from app.modules.library.models import MediaFile
    from app.modules.library.router import media_path

    media_id = (company.settings or {}).get("logo_media_id") if company else None
    media = db.get(MediaFile, uuid.UUID(media_id)) if media_id else None
    if media is None or not media_path(media.sha256).exists():
        raise NotFound("No logo", code="NO_LOGO")
    return FileResponse(media_path(media.sha256), media_type=media.mime, headers={"Cache-Control": "max-age=300"})


@router.get("/company", response_model=dict)
def get_company(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    c = db.get(Company, ctx.company_id)
    return {"id": str(c.id), "code": c.code, "name": c.name, "version": c.version,
            "settings": get_company_settings(db, ctx.company_id).model_dump(mode="json"), "branding": branding(db, c)}


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
        new = body.settings.model_dump(mode="json")
        new["logo_media_id"] = (c.settings or {}).get("logo_media_id")  # only changed via /company/logo
        c.settings = new
    audit(db, c, "update", before)
    db.commit()
    return get_company(dc)
