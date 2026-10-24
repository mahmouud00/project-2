from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.common import ORMModel, Page, PageParams, Record, VersionedUpdate, paginate
from app.auth.permissions import PERMISSIONS
from app.auth.security import hash_password
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.licensing.service import enforce_branch_limit, enforce_user_limit
from app.modules.org.models import AuditLog, Branch, Device, Role, User, UserBranchRole
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(tags=["org"])


def get_or_404(db, model, obj_id):
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise NotFound(f"{model.__name__} not found")
    return obj


# ---------------------------------------------------------------- branches
class BranchIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field("factory", pattern="^(factory|warehouse|showroom|office)$")


class BranchUpdate(VersionedUpdate):
    name: str | None = None
    kind: str | None = Field(None, pattern="^(factory|warehouse|showroom|office)$")
    is_active: bool | None = None


class BranchOut(Record):
    code: str
    name: str
    kind: str
    is_active: bool


@router.get("/branches", response_model=Page[BranchOut])
def list_branches(params: PageParams = Depends(), dc=Depends(get_db_and_ctx)):
    db, _ = dc
    stmt = select(Branch).where(Branch.deleted_at.is_(None)).order_by(Branch.code)
    return paginate(db, stmt, params, BranchOut)


@router.post("/branches", response_model=BranchOut, status_code=201)
def create_branch(body: BranchIn, dc=Depends(require("org.manage"))):
    db, ctx = dc
    enforce_branch_limit(db, ctx.company_id)
    if db.scalar(select(Branch).where(Branch.code == body.code)):
        raise Conflict("Branch code exists", code="DUPLICATE_CODE")
    branch = Branch(**body.model_dump())
    db.add(branch)
    db.flush()
    audit(db, branch, "create")
    db.commit()
    return branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(branch_id: uuid.UUID, body: BranchUpdate, dc=Depends(require("org.manage"))):
    db, _ = dc
    branch = get_or_404(db, Branch, branch_id)
    check_version(branch, body.version)
    before = snapshot(branch)
    apply_changes(branch, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, branch, "update", before)
    db.commit()
    return branch


# ---------------------------------------------------------------- roles
class RoleIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str
    permissions: list[str]


class RoleUpdate(VersionedUpdate):
    name: str | None = None
    permissions: list[str] | None = None


class RoleOut(Record):
    code: str
    name: str
    permissions: list[str]
    is_builtin: bool


def _check_perms(perms: list[str] | None) -> None:
    unknown = sorted(set(perms or []) - set(PERMISSIONS))
    if unknown:
        raise ValidationFailed("Unknown permissions", code="UNKNOWN_PERMISSION", details=unknown)


@router.get("/permissions")
def list_permissions(dc=Depends(require("users.manage"))):
    return [{"code": k, "name": v} for k, v in PERMISSIONS.items()]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(dc=Depends(require("users.manage"))):
    db, _ = dc
    return db.scalars(select(Role).order_by(Role.code)).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(body: RoleIn, dc=Depends(require("users.manage"))):
    db, _ = dc
    _check_perms(body.permissions)
    if db.scalar(select(Role).where(Role.code == body.code)):
        raise Conflict("Role code exists", code="DUPLICATE_CODE")
    role = Role(**body.model_dump())
    db.add(role)
    db.flush()
    audit(db, role, "create")
    db.commit()
    return role


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: uuid.UUID, body: RoleUpdate, dc=Depends(require("users.manage"))):
    db, _ = dc
    role = get_or_404(db, Role, role_id)
    check_version(role, body.version)
    _check_perms(body.permissions)
    before = snapshot(role)
    apply_changes(role, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, role, "update", before)
    db.commit()
    return role


# ---------------------------------------------------------------- users
class Assignment(BaseModel):
    role_id: uuid.UUID
    branch_id: uuid.UUID | None = None


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8)
    full_name: str
    phone: str | None = None
    email: str | None = None
    assignments: list[Assignment] = []


class UserUpdate(VersionedUpdate):
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)
    assignments: list[Assignment] | None = None


class AssignmentOut(ORMModel):
    role_id: uuid.UUID
    branch_id: uuid.UUID | None


class UserOut(Record):
    username: str
    full_name: str
    phone: str | None
    email: str | None
    is_active: bool
    must_change_password: bool
    assignments: list[AssignmentOut] = []


def _user_out(db, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.assignments = [AssignmentOut.model_validate(a) for a in
                       db.scalars(select(UserBranchRole).where(UserBranchRole.user_id == user.id)).all()]
    return out


def _set_assignments(db, user: User, assignments: list[Assignment]) -> None:
    for a in assignments:
        get_or_404(db, Role, a.role_id)
        if a.branch_id:
            get_or_404(db, Branch, a.branch_id)
    for old in db.scalars(select(UserBranchRole).where(UserBranchRole.user_id == user.id)).all():
        db.delete(old)
    db.flush()
    for a in assignments:
        db.add(UserBranchRole(user_id=user.id, role_id=a.role_id, branch_id=a.branch_id))


@router.get("/users", response_model=Page[UserOut])
def list_users(params: PageParams = Depends(), dc=Depends(require("users.manage"))):
    db, _ = dc
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.username)
    page = paginate(db, stmt, params, UserOut)
    page["items"] = [_user_out(db, db.get(User, u.id)) for u in page["items"]]
    return page


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, dc=Depends(require("users.manage"))):
    db, ctx = dc
    enforce_user_limit(db, ctx.company_id)
    if db.scalar(select(User).where(User.username == body.username)):
        raise Conflict("Username exists", code="DUPLICATE_USERNAME")
    data = body.model_dump(exclude={"password", "assignments"})
    user = User(**data, password_hash=hash_password(body.password), must_change_password=True)
    db.add(user)
    db.flush()
    _set_assignments(db, user, body.assignments)
    audit(db, user, "create")
    db.commit()
    return _user_out(db, user)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, dc=Depends(require("users.manage"))):
    db, _ = dc
    return _user_out(db, get_or_404(db, User, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, dc=Depends(require("users.manage"))):
    db, _ = dc
    user = get_or_404(db, User, user_id)
    check_version(user, body.version)
    before = snapshot(user)
    data = body.model_dump(exclude_unset=True, exclude={"version", "password", "assignments"})
    apply_changes(user, data)
    if body.password:
        user.password_hash = hash_password(body.password)
        user.must_change_password = True
    if body.assignments is not None:
        _set_assignments(db, user, body.assignments)
        user.updated_at = datetime.now().astimezone()  # bump version when only roles change
    audit(db, user, "update", before)
    db.commit()
    return _user_out(db, user)


# ---------------------------------------------------------------- devices
class DeviceOut(ORMModel):
    id: uuid.UUID
    device_key: str
    name: str
    client_version: str
    platform: str
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime


class DeviceUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(dc=Depends(require("system.manage"))):
    db, _ = dc
    return db.scalars(select(Device).order_by(Device.last_seen_at.desc())).all()


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(device_id: uuid.UUID, body: DeviceUpdate, dc=Depends(require("system.manage"))):
    db, _ = dc
    device = get_or_404(db, Device, device_id)
    apply_changes(device, body.model_dump(exclude_unset=True))
    db.commit()
    return device


# ---------------------------------------------------------------- audit
class AuditOut(ORMModel):
    id: uuid.UUID
    at: datetime
    user_id: uuid.UUID | None
    entity: str
    entity_id: str
    action: str
    changes: dict
    note: str | None


@router.get("/audit-log", response_model=Page[AuditOut])
def list_audit(entity: str | None = None, entity_id: str | None = None, params: PageParams = Depends(),
               dc=Depends(require("audit.read"))):
    db, _ = dc
    stmt = select(AuditLog).order_by(AuditLog.at.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    return paginate(db, stmt, params, AuditOut)
