"""Login / refresh / logout. Runs on the system session because the company
is not known until the credentials are checked; every query here filters by
company explicitly."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.security import (create_access_token, hash_password, hash_token, needs_rehash,
                               new_refresh_token, verify_password)
from app.core.config import get_settings
from app.core.errors import AppError, Unauthorized
from app.db.base import PLATFORM_COMPANY_ID
from app.modules.org.models import Company, Device, RefreshToken, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_company(db: Session, company_code: str | None) -> Company:
    if company_code:
        company = db.scalar(select(Company).where(Company.code == company_code))
    else:
        # Offline installs have exactly one customer company (plus the platform row).
        companies = db.scalars(select(Company).where(Company.id != PLATFORM_COMPANY_ID, Company.is_active)).all()
        company = companies[0] if len(companies) == 1 else None
        if company is None and len(companies) > 1:
            raise Unauthorized("Company code required", code="COMPANY_REQUIRED")
    if company is None or not company.is_active:
        raise Unauthorized("Invalid credentials", code="INVALID_CREDENTIALS")
    return company


def register_device(db: Session, company_id: uuid.UUID, device_key: str, name: str, client_version: str,
                    platform: str) -> Device:
    from app.licensing.service import enforce_device_limit

    device = db.scalar(select(Device).where(Device.company_id == company_id, Device.device_key == device_key))
    if device is None:
        enforce_device_limit(db, company_id)
        device = Device(company_id=company_id, device_key=device_key, name=name)
        db.add(device)
    elif not device.is_active:
        raise Unauthorized("Device disabled", code="DEVICE_DISABLED")
    device.client_version = client_version or device.client_version
    device.platform = platform or device.platform
    device.last_seen_at = _now()
    db.flush()
    return device


def _issue(db: Session, user: User, device: Device | None, family_id: uuid.UUID | None = None) -> dict:
    s = get_settings()
    raw, digest = new_refresh_token()
    db.add(RefreshToken(company_id=user.company_id, user_id=user.id, device_id=device.id if device else None,
                        family_id=family_id or uuid.uuid4(), token_hash=digest,
                        expires_at=_now() + timedelta(days=s.refresh_token_days)))
    return {
        "access_token": create_access_token(user_id=user.id, company_id=user.company_id,
                                            device_id=device.id if device else None),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": s.access_token_minutes * 60,
        "user_id": str(user.id),
        "company_id": str(user.company_id),
        "must_change_password": user.must_change_password,
    }


def login(db: Session, *, company_code: str | None, username: str, password: str, device_key: str,
          device_name: str = "", client_version: str = "", platform: str = "") -> dict:
    s = get_settings()
    company = resolve_company(db, company_code)
    user = db.scalar(select(User).where(User.company_id == company.id, User.username == username,
                                        User.deleted_at.is_(None)).with_for_update())
    if user is None:
        verify_password(hash_password("timing-equaliser"), password)
        raise Unauthorized("Invalid credentials", code="INVALID_CREDENTIALS")
    if user.locked_until and user.locked_until > _now():
        raise AppError("Account temporarily locked", code="ACCOUNT_LOCKED", status_code=423)
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= s.login_max_failures:
            user.locked_until = _now() + timedelta(minutes=s.login_lock_minutes)
            user.failed_logins = 0
        db.commit()
        raise Unauthorized("Invalid credentials", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise Unauthorized("User disabled", code="USER_DISABLED")
    user.failed_logins = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    device = register_device(db, company.id, device_key, device_name, client_version, platform)
    tokens = _issue(db, user, device)
    db.commit()
    return tokens


def refresh(db: Session, raw_token: str) -> dict:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update())
    if token is None:
        raise Unauthorized("Invalid refresh token", code="TOKEN_INVALID")
    if token.used_at is not None or token.revoked_at is not None:
        # Re-use of a rotated token: assume theft, kill the whole family.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
        db.commit()
        raise Unauthorized("Refresh token reused", code="TOKEN_REUSED")
    if token.expires_at < _now():
        raise Unauthorized("Refresh token expired", code="TOKEN_EXPIRED")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("User disabled", code="USER_DISABLED")
    device = db.get(Device, token.device_id) if token.device_id else None
    if device is not None and not device.is_active:
        raise Unauthorized("Device disabled", code="DEVICE_DISABLED")
    token.used_at = _now()
    if device is not None:
        device.last_seen_at = _now()
    tokens = _issue(db, user, device, family_id=token.family_id)
    db.commit()
    return tokens


def logout(db: Session, raw_token: str) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if token is not None:
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
        db.commit()
