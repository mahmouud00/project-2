"""Company bootstrap and org administration."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import DEFAULT_ROLES, PERMISSIONS, PLATFORM_PERMISSIONS
from app.auth.security import hash_password
from app.db.base import PLATFORM_COMPANY_ID
from app.modules.org.models import Branch, Company, Role, User, UserBranchRole


def ensure_platform_company(db: Session) -> Company:
    company = db.get(Company, PLATFORM_COMPANY_ID)
    if company is None:
        company = Company(id=PLATFORM_COMPANY_ID, company_id=PLATFORM_COMPANY_ID, code="__platform__",
                          name="MYTech Solutions (Library)")
        db.add(company)
        db.flush()
        db.add(Role(company_id=PLATFORM_COMPANY_ID, code="platform_admin", name="مدير المنصة", is_builtin=True,
                    permissions=list(PERMISSIONS) + list(PLATFORM_PERMISSIONS)))
        db.flush()
    return company


def create_company(db: Session, *, code: str, name: str, admin_username: str, admin_password: str,
                   admin_full_name: str = "مدير النظام", branch_name: str = "الفرع الرئيسي",
                   company_id: uuid.UUID | None = None) -> tuple[Company, User]:
    """Create a company with built-in roles, a main branch and an admin user.
    Runs on the system session (vendor tool / installer / tests)."""
    ensure_platform_company(db)
    cid = company_id or uuid.uuid4()
    company = Company(id=cid, company_id=cid, code=code, name=name)
    db.add(company)
    db.flush()
    roles = {}
    for role_code, spec in DEFAULT_ROLES.items():
        roles[role_code] = Role(company_id=cid, code=role_code, name=spec["name"],
                                permissions=list(spec["permissions"]), is_builtin=True)
        db.add(roles[role_code])
    db.add(Branch(company_id=cid, code="MAIN", name=branch_name))
    admin = User(company_id=cid, username=admin_username, password_hash=hash_password(admin_password),
                 full_name=admin_full_name, must_change_password=True)
    db.add(admin)
    db.flush()
    db.add(UserBranchRole(company_id=cid, user_id=admin.id, branch_id=None, role_id=roles["admin"].id))
    db.flush()
    return company, admin


def create_platform_admin(db: Session, username: str, password: str, full_name: str = "MYTech") -> User:
    ensure_platform_company(db)
    role = db.scalar(select(Role).where(Role.company_id == PLATFORM_COMPANY_ID, Role.code == "platform_admin"))
    user = User(company_id=PLATFORM_COMPANY_ID, username=username, password_hash=hash_password(password),
                full_name=full_name)
    db.add(user)
    db.flush()
    db.add(UserBranchRole(company_id=PLATFORM_COMPANY_ID, user_id=user.id, branch_id=None, role_id=role.id))
    db.flush()
    return user
