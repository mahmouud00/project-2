from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app.auth import service
from app.auth.security import hash_password, verify_password
from app.core.errors import ValidationFailed
from app.db.session import iter_system_session
from app.modules.org.models import User
from app.tenancy.context import get_db_and_ctx

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    company_code: str | None = None
    username: str
    password: str
    device_key: str = Field(min_length=4, max_length=100)
    device_name: str = ""
    client_version: str = ""
    platform: str = ""
    otp: str | None = Field(None, max_length=10)   # the authenticator app's code, for users with two-step login


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/login")
def login(body: LoginIn, db=Depends(iter_system_session)):
    return service.login(db, **body.model_dump())


@router.post("/token")
def token(form: OAuth2PasswordRequestForm = Depends(), db=Depends(iter_system_session)):
    """OAuth2 password form (used by the "Authorize" button of /api/docs).
    client_id = company code (needed when the server hosts several companies)."""
    tokens = service.login(db, company_code=form.client_id or None, username=form.username, password=form.password,
                           device_key="api-docs-browser", device_name="API docs")
    return {"access_token": tokens["access_token"], "token_type": "bearer"}


@router.post("/refresh")
def refresh(body: RefreshIn, db=Depends(iter_system_session)):
    return service.refresh(db, body.refresh_token)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db=Depends(iter_system_session)):
    service.logout(db, body.refresh_token)


@router.get("/me")
def me(dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    user = db.get(User, ctx.user_id)
    return {
        "id": str(user.id), "username": user.username, "full_name": user.full_name,
        "company_id": str(ctx.company_id), "device_id": str(ctx.device_id) if ctx.device_id else None,
        "must_change_password": user.must_change_password,
        "two_factor_enabled": user.totp_enabled_at is not None,
        "two_factor_required": two_factor_required(db, ctx) and user.totp_enabled_at is None,
        "grants": {str(k) if k else "*": sorted(v) for k, v in ctx.grants.items()},
    }


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    user = db.get(User, ctx.user_id)
    if not verify_password(user.password_hash, body.current_password):
        raise ValidationFailed("Current password is wrong", code="WRONG_PASSWORD")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()


# ---------------------------------------------------------------- two-step login (authenticator app)
def two_factor_required(db, ctx) -> bool:
    """The company asks administrators (who manage users) to use two-step login."""
    from app.modules.org.settings import get_company_settings
    return bool(get_company_settings(db, ctx.company_id).two_factor_for_admins) and ctx.can("users.manage")


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class DisableIn(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=10)


@router.post("/2fa/setup")
def two_factor_setup(dc=Depends(get_db_and_ctx)):
    """A new secret for the authenticator app (scan the QR or type the key). Not active until a code is confirmed."""
    import segno

    from app.auth import totp
    from app.core.errors import Conflict
    from app.modules.org.models import Company

    db, ctx = dc
    user = db.get(User, ctx.user_id)
    if user.totp_enabled_at is not None:
        raise Conflict("Two-step login is already on", code="TWO_FACTOR_ON")
    secret = totp.new_secret()
    user.totp_secret = totp.seal(secret)
    company = db.get(Company, ctx.company_id)
    link = totp.uri(secret, user.username, f"MYTech {company.code}")
    db.commit()
    return {"secret": secret, "uri": link, "qr_svg": segno.make(link, error="m").svg_inline(scale=4, border=2)}


@router.post("/2fa/enable", status_code=204)
def two_factor_enable(body: CodeIn, dc=Depends(get_db_and_ctx)):
    from datetime import datetime, timezone

    from app.auth import totp
    from app.core.audit import audit, snapshot

    db, ctx = dc
    user = db.get(User, ctx.user_id)
    secret = totp.unseal(user.totp_secret)
    step = totp.verify(secret, body.code, None) if secret and user.totp_enabled_at is None else None
    if step is None:
        raise ValidationFailed("Wrong code: check the phone's time and try the new code", code="OTP_INVALID")
    before = snapshot(user)
    user.totp_enabled_at, user.totp_last_step = datetime.now(timezone.utc), step
    audit(db, user, "update", before, note="two-step login turned on")
    db.commit()


@router.post("/2fa/disable", status_code=204)
def two_factor_disable(body: DisableIn, dc=Depends(get_db_and_ctx)):
    from app.auth import totp
    from app.core.audit import audit, snapshot
    from app.core.errors import Conflict

    db, ctx = dc
    user = db.get(User, ctx.user_id)
    if user.totp_enabled_at is None:
        return
    if not verify_password(user.password_hash, body.password):
        raise ValidationFailed("Current password is wrong", code="WRONG_PASSWORD")
    secret = totp.unseal(user.totp_secret)
    if not secret or totp.verify(secret, body.code, user.totp_last_step) is None:
        raise ValidationFailed("Wrong code", code="OTP_INVALID")
    from app.modules.org.settings import get_company_settings
    if get_company_settings(db, ctx.company_id).two_factor_for_admins and ctx.can("users.manage"):
        raise Conflict("The company requires two-step login for administrators", code="TWO_FACTOR_REQUIRED")
    before = snapshot(user)
    user.totp_secret, user.totp_enabled_at, user.totp_last_step = None, None, None
    audit(db, user, "update", before, note="two-step login turned off")
    db.commit()


# ---------------------------------------------------------------- where I am signed in
@router.get("/sessions")
def my_sessions(dc=Depends(get_db_and_ctx)):
    """The devices this user is signed in on (live sign-ins), newest first; `current` is this one."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.modules.org.models import Device, RefreshToken

    db, ctx = dc
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(RefreshToken).where(RefreshToken.user_id == ctx.user_id, RefreshToken.revoked_at.is_(None),
                                                 RefreshToken.used_at.is_(None), RefreshToken.expires_at > now)
                      .order_by(RefreshToken.created_at.desc())).all()
    out, seen = [], set()
    for t in rows:
        if t.family_id in seen:
            continue
        seen.add(t.family_id)
        d = db.get(Device, t.device_id) if t.device_id else None
        out.append({"id": str(t.family_id), "device": (d.name or d.platform or "جهاز") if d else "جهاز",
                    "platform": d.platform if d else "", "last_seen_at": (d.last_seen_at if d else t.created_at),
                    "signed_in_at": t.created_at, "current": bool(d and ctx.device_id == d.id)})
    return out


@router.post("/sessions/{family_id}/revoke", status_code=204)
def revoke_session(family_id: str, dc=Depends(get_db_and_ctx)):
    """Sign that device out (it can stay in at most until its short access token ends)."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.modules.org.models import RefreshToken

    db, ctx = dc
    db.execute(update(RefreshToken).where(RefreshToken.family_id == _uuid.UUID(family_id), RefreshToken.user_id == ctx.user_id,
                                          RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    db.commit()
