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
