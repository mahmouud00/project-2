from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, UploadFile, WebSocket, WebSocketDisconnect
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


def _branding_company(db, company_code: str | None):
    from sqlalchemy import select

    from app.core.errors import NotFound
    from app.db.base import PLATFORM_COMPANY_ID
    from app.modules.org.models import Company

    stmt = select(Company).where(Company.is_active, Company.id != PLATFORM_COMPANY_ID)
    if company_code:
        stmt = stmt.where(Company.code == company_code)
    elif get_settings().is_online:
        raise NotFound("Company code required", code="COMPANY_REQUIRED")
    companies = db.scalars(stmt.limit(2)).all()
    if len(companies) != 1:
        raise NotFound("Company not found")
    return companies[0]


@router.get("/branding")
def public_branding(company_code: str | None = None, db=Depends(iter_system_session)):
    """(Public) company name and logo for the login screen. No personal data."""
    from app.modules.org.settings import branding

    b = branding(db, _branding_company(db, company_code))
    return {k: b[k] for k in ("company_code", "name", "has_logo", "accent_color")}


@router.get("/branding/logo")
def public_logo(company_code: str | None = None, db=Depends(iter_system_session)):
    from app.modules.org.settings import _logo_response

    return _logo_response(db, _branding_company(db, company_code))


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


def _install_license(raw: bytes) -> dict:
    s = get_settings()
    if s.is_online:
        raise ValidationFailed("Online mode uses subscriptions", code="NOT_OFFLINE")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValidationFailed("Not a licence file", code="LICENSE_FILE_INVALID")
    if not isinstance(doc, dict) or not isinstance(doc.get("payload"), dict):
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


@router.post("/license")
async def upload_license(file: UploadFile, dc=Depends(require("system.manage"))):
    """Offline only: install a signed licence file issued by MYTech."""
    return _install_license(await file.read())


def _server_entitlements():
    """Offline: the server's licence file (the same for its one company)."""
    if get_settings().is_online:
        raise ValidationFailed("Online mode uses subscriptions", code="NOT_OFFLINE")
    return get_license_provider().entitlements(None, uuid.UUID(int=0))


@router.get("/activation")
def activation_status():
    """(Public, offline) licence state for the login screen: nobody can log in before the first licence,
    so the fingerprint and the reason must be readable without a token. No personal data."""
    out = _server_entitlements().as_dict()
    out["machine_fingerprint"] = machine_fingerprint()
    return out


@router.post("/activation")
async def activate(file: UploadFile):
    """(Public, offline) install a licence while there is no usable one (first install, wrong machine,
    expired). A working licence can only be replaced by a logged-in administrator (POST /system/license).
    The file must be signed by MYTech and issued for this machine, so this cannot unlock anything."""
    if _server_entitlements().status in ("valid", "grace"):
        from app.core.errors import Forbidden
        raise Forbidden("A licence is already active", code="LICENSE_ACTIVE")
    return _install_license(await file.read())


# ---------------------------------------------------------------- backups
def _require_backup_admin(ctx) -> None:
    ctx.require("system.manage")
    if get_settings().is_online and not ctx.is_platform:
        # online: one database holds every company; backups are run by MYTech
        from app.core.errors import Forbidden
        raise Forbidden("Backups are managed by MYTech", code="PLATFORM_ONLY")


@router.get("/backups")
def backups(dc=Depends(get_db_and_ctx)):
    from app.ops.backup import last_status, list_backups

    _require_backup_admin(dc[1])
    return {"last_status": last_status(), "backups": list_backups(),
            "directory": str(get_settings().backup_dir), "keep": get_settings().backup_keep}


@router.post("/backups", status_code=201)
def backup_now(dc=Depends(get_db_and_ctx)):
    from app.core.errors import AppError
    from app.ops.backup import BackupError, run_backup, verify

    _require_backup_admin(dc[1])
    try:
        path = run_backup("manual")
    except BackupError as e:
        raise AppError(str(e), code="BACKUP_FAILED", status_code=500)
    return verify(path)


# ---------------------------------------------------------------- live events
@router.websocket("/events")
async def events(websocket: WebSocket, token: str | None = None):
    """Live change feed: {"entity", "id", "action", "at"} for the caller's company.
    Browsers pass the access token as ?token=..., other clients may use the header."""
    import asyncio
    import uuid

    from app.auth.security import decode_access_token
    from app.core.errors import Unauthorized
    from app.ops.events import hub

    raw = token or (websocket.headers.get("authorization", "").split(" ", 1)[-1] or None)
    try:
        claims = decode_access_token(raw or "")
    except Unauthorized:
        await websocket.close(code=4401)
        return
    company_id = uuid.UUID(claims["cid"])
    await websocket.accept()
    queue = hub.subscribe(company_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            event.pop("cid", None)
            await websocket.send_json({"type": "change", **event})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(company_id, queue)
