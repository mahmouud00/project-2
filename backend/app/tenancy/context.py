"""Per-request context: who is calling, for which company, with what rights."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import Depends, Header, Request
from sqlalchemy import select

from app.auth.security import decode_access_token
from app.core.errors import Forbidden, LicenseError, Unauthorized
from app.db.base import PLATFORM_COMPANY_ID
from app.db.session import TenantSession, tenant_session


@dataclass
class RequestContext:
    company_id: uuid.UUID
    user_id: uuid.UUID
    device_id: uuid.UUID | None
    # branch_id (None = all branches) -> permission codes
    grants: dict[uuid.UUID | None, set[str]] = field(default_factory=dict)
    ip: str | None = None
    entitlements: object | None = None

    @property
    def is_platform(self) -> bool:
        return self.company_id == PLATFORM_COMPANY_ID

    def can(self, permission: str, branch_id: uuid.UUID | None = None) -> bool:
        if permission in self.grants.get(None, set()):
            return True
        if branch_id is None:
            return any(permission in perms for perms in self.grants.values())
        return permission in self.grants.get(branch_id, set())

    def branches_for(self, permission: str) -> set[uuid.UUID] | None:
        """Branches where the permission applies; None means all branches."""
        if permission in self.grants.get(None, set()):
            return None
        return {b for b, perms in self.grants.items() if b is not None and permission in perms}

    def require(self, permission: str, branch_id: uuid.UUID | None = None) -> None:
        if not self.can(permission, branch_id):
            raise Forbidden(f"Missing permission {permission}", code="PERMISSION_DENIED",
                            details={"permission": permission, "branch_id": str(branch_id) if branch_id else None})


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def get_db_and_ctx(request: Request, authorization: str | None = Header(default=None)) -> Iterator[tuple[TenantSession, RequestContext]]:
    from app.modules.org.models import Role, User, UserBranchRole

    claims = decode_access_token(_bearer(authorization))
    company_id = uuid.UUID(claims["cid"])
    user_id = uuid.UUID(claims["sub"])
    device_id = uuid.UUID(claims["did"]) if claims.get("did") else None
    db = tenant_session(company_id, user_id)
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise Unauthorized("User disabled", code="USER_DISABLED")
        rows = db.execute(select(UserBranchRole.branch_id, Role.permissions)
                          .join(Role, Role.id == UserBranchRole.role_id)
                          .where(UserBranchRole.user_id == user_id)).all()
        grants: dict[uuid.UUID | None, set[str]] = {}
        for branch_id, perms in rows:
            grants.setdefault(branch_id, set()).update(perms or [])
        db.info["device_id"] = device_id
        ctx = RequestContext(company_id, user_id, device_id, grants,
                             ip=request.client.host if request.client else None)
        _license_gate(db, ctx, request)
        request.state.ctx = ctx
        yield db, ctx
    finally:
        # Endpoints commit explicitly; anything left uncommitted is discarded.
        db.rollback()
        db.close()


_LICENSE_EXEMPT = ("/api/v1/system/license", "/api/v1/auth/")


def _license_gate(db: TenantSession, ctx: RequestContext, request: Request) -> None:
    from app.licensing.service import entitlements

    if request.url.path.startswith(_LICENSE_EXEMPT):
        return
    ent = entitlements(db, ctx.company_id)
    ctx.entitlements = ent
    if not ent.can_read:
        raise LicenseError("Licence not valid", code="LICENSE_INVALID", details=ent.as_dict())
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not ent.can_write:
        raise LicenseError("Licence expired: read-only mode", code="LICENSE_READ_ONLY", details=ent.as_dict())


def require(permission: str):
    """Dependency factory: user must hold `permission` in at least one branch."""
    def _dep(dc=Depends(get_db_and_ctx)):
        dc[1].require(permission)
        return dc
    return _dep


def require_module(module: str):
    """Dependency: the company's licence/subscription must include `module`."""
    def _dep(dc=Depends(get_db_and_ctx)):
        from app.licensing.service import require_module as _check
        _check(dc[0], dc[1].company_id, module)
        return dc
    return _dep
