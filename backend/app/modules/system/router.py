from __future__ import annotations

import json

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db.session import iter_system_session
from app.licensing.fingerprint import machine_fingerprint
from app.licensing.provider import (MODULES, OfflineFileLicenseProvider, evaluate_license_document,
                                    get_license_provider)
from app.licensing.service import entitlements
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def info():
    """Public: used by device discovery and version compatibility checks."""
    s = get_settings()
    return {"product": s.app_name, "version": s.version, "mode": s.app_mode.value,
            "min_client_version": s.min_client_version, "api": "/api/v1"}


@router.get("/health")
def health(db=Depends(iter_system_session)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/license")
def license_status(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    ent = entitlements(db, ctx.company_id)
    out = ent.as_dict()
    out["module_names"] = MODULES
    if not get_settings().is_online:
        out["machine_fingerprint"] = machine_fingerprint()
    return out


@router.post("/license")
async def upload_license(file: UploadFile, dc=Depends(require("system.manage"))):
    """Offline only: install a signed licence file issued by MYTech."""
    s = get_settings()
    if s.is_online:
        raise ValidationFailed("Online mode uses subscriptions", code="NOT_OFFLINE")
    raw = await file.read()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationFailed("Not a licence file", code="LICENSE_FILE_INVALID")
    ent = evaluate_license_document(doc, machine_fingerprint())
    if ent.status not in ("valid", "grace"):
        raise ValidationFailed("Licence rejected", code="LICENSE_REJECTED", details=ent.as_dict())
    s.license_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = s.license_file.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(s.license_file)
    provider = get_license_provider()
    if isinstance(provider, OfflineFileLicenseProvider):
        provider.invalidate()
    return ent.as_dict()
