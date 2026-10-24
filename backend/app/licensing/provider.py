"""One licensing interface, two implementations.

The rest of the system only calls `get_license_provider().entitlements(...)`
and never asks which mode it is running in.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import PLATFORM_COMPANY_ID
from app.licensing.fingerprint import machine_fingerprint
from app.licensing.signing import verify_document

MODULES = {
    "core": "النواة الإدارية",
    "manufacturing": "التصنيع",
    "mfg.upvc": "تصنيع UPVC",
    "mfg.shutter": "تصنيع الشاتر",
    "mfg.aluminum": "تصنيع الألومنيوم",
}

# status -> can read / can write
STATUS_VALID, STATUS_GRACE, STATUS_EXPIRED, STATUS_INVALID, STATUS_MISSING = (
    "valid", "grace", "expired", "invalid", "missing")


@dataclass
class Entitlements:
    status: str
    modules: set[str] = field(default_factory=set)
    max_devices: int | None = None
    max_users: int | None = None
    max_branches: int | None = None
    expires_at: datetime | None = None
    reason: str | None = None
    license_id: str | None = None
    company_code: str | None = None

    @property
    def can_read(self) -> bool:
        return self.status in (STATUS_VALID, STATUS_GRACE, STATUS_EXPIRED)

    @property
    def can_write(self) -> bool:
        return self.status in (STATUS_VALID, STATUS_GRACE)

    def has_module(self, module: str) -> bool:
        return module in self.modules

    def as_dict(self) -> dict:
        return {
            "status": self.status, "modules": sorted(self.modules), "max_devices": self.max_devices,
            "max_users": self.max_users, "max_branches": self.max_branches,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason": self.reason, "license_id": self.license_id, "company_code": self.company_code,
            "can_read": self.can_read, "can_write": self.can_write,
        }


FULL = Entitlements(STATUS_VALID, set(MODULES))


class LicenseProvider(Protocol):
    def entitlements(self, db: Session, company_id: uuid.UUID) -> Entitlements: ...


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _time_status(expires_at: datetime | None, grace_days: int) -> tuple[str, str | None]:
    if expires_at is None:
        return STATUS_VALID, None
    now = datetime.now(timezone.utc)
    if now <= expires_at:
        return STATUS_VALID, None
    if now <= expires_at + timedelta(days=grace_days):
        return STATUS_GRACE, "expired_in_grace"
    return STATUS_EXPIRED, "expired"


def evaluate_license_document(doc: dict, fingerprint: str) -> Entitlements:
    """Pure function: signed licence document -> entitlements."""
    if not verify_document(doc):
        return Entitlements(STATUS_INVALID, reason="bad_signature")
    p = doc["payload"]
    if p.get("machine_fingerprint") not in (fingerprint, "*"):
        return Entitlements(STATUS_INVALID, reason="machine_mismatch", license_id=p.get("license_id"))
    expires_at = _parse_dt(p.get("expires_at"))
    status, reason = _time_status(expires_at, int(p.get("grace_days", get_settings().license_grace_days)))
    return Entitlements(status, set(p.get("modules", [])), p.get("max_devices"), p.get("max_users"),
                        p.get("max_branches"), expires_at, reason, p.get("license_id"), p.get("company_code"))


class OfflineFileLicenseProvider:
    def __init__(self) -> None:
        self._cache: tuple[float, Entitlements] | None = None

    def entitlements(self, db: Session, company_id: uuid.UUID) -> Entitlements:
        if company_id == PLATFORM_COMPANY_ID:
            return FULL
        path = get_settings().license_file
        if not path.exists():
            return Entitlements(STATUS_MISSING, reason="no_license_file")
        mtime = path.stat().st_mtime
        if self._cache and self._cache[0] == mtime:
            cached = self._cache[1]
            # time-based status can change while cached
            if cached.status in (STATUS_VALID, STATUS_GRACE, STATUS_EXPIRED) and cached.expires_at:
                return self._load(path, mtime)
            return cached
        return self._load(path, mtime)

    def _load(self, path, mtime) -> Entitlements:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ent = Entitlements(STATUS_INVALID, reason="unreadable")
        else:
            ent = evaluate_license_document(doc, machine_fingerprint())
        self._cache = (mtime, ent)
        return ent

    def invalidate(self) -> None:
        self._cache = None


class OnlineSubscriptionProvider:
    def entitlements(self, db: Session, company_id: uuid.UUID) -> Entitlements:
        from app.licensing.models import Subscription

        if company_id == PLATFORM_COMPANY_ID:
            return FULL
        sub = db.scalar(select(Subscription).where(Subscription.company_id == company_id, Subscription.is_active)
                        .order_by(Subscription.expires_at.desc()).execution_options(skip_tenant_filter=True))
        if sub is None:
            return Entitlements(STATUS_MISSING, reason="no_subscription")
        status, reason = _time_status(sub.expires_at, get_settings().license_grace_days)
        return Entitlements(status, set(sub.modules), sub.max_devices, sub.max_users, sub.max_branches,
                            sub.expires_at, reason, str(sub.id))


_provider: LicenseProvider | None = None


def get_license_provider() -> LicenseProvider:
    global _provider
    if _provider is None:
        _provider = OnlineSubscriptionProvider() if get_settings().is_online else OfflineFileLicenseProvider()
    return _provider


def set_license_provider(provider: LicenseProvider | None) -> None:
    global _provider
    _provider = provider
