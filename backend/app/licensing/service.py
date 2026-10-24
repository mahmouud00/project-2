"""Licence enforcement points (single place for every limit)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import LicenseError
from app.licensing.provider import get_license_provider


def entitlements(db: Session, company_id: uuid.UUID):
    return get_license_provider().entitlements(db, company_id)


def _count(db: Session, model, company_id: uuid.UUID, *extra) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.company_id == company_id, *extra)) or 0


def enforce_device_limit(db: Session, company_id: uuid.UUID) -> None:
    from app.modules.org.models import Device

    ent = entitlements(db, company_id)
    if not ent.can_read:
        raise LicenseError("Licence not valid", code="LICENSE_INVALID", details=ent.as_dict())
    if ent.max_devices is not None and _count(db, Device, company_id, Device.is_active) >= ent.max_devices:
        raise LicenseError("Device limit reached", code="LICENSE_DEVICE_LIMIT", details={"max_devices": ent.max_devices})


def enforce_user_limit(db: Session, company_id: uuid.UUID) -> None:
    from app.modules.org.models import User

    ent = entitlements(db, company_id)
    if ent.max_users is not None and _count(db, User, company_id, User.deleted_at.is_(None), User.is_active) >= ent.max_users:
        raise LicenseError("User limit reached", code="LICENSE_USER_LIMIT", details={"max_users": ent.max_users})


def enforce_branch_limit(db: Session, company_id: uuid.UUID) -> None:
    from app.modules.org.models import Branch

    ent = entitlements(db, company_id)
    if ent.max_branches is not None and _count(db, Branch, company_id, Branch.deleted_at.is_(None)) >= ent.max_branches:
        raise LicenseError("Branch limit reached", code="LICENSE_BRANCH_LIMIT", details={"max_branches": ent.max_branches})


def require_module(db: Session, company_id: uuid.UUID, module: str) -> None:
    ent = entitlements(db, company_id)
    if not ent.has_module(module):
        raise LicenseError(f"Module {module} not licensed", code="MODULE_NOT_LICENSED", details={"module": module})
