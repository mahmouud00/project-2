"""Engines and sessions.

Two engines:
- app engine   (role mytech_app): every request. Row-Level Security is enforced;
  each transaction runs `set_config('app.company_id', ..., true)`.
- system engine (role mytech_system, BYPASSRLS): only for login lookup,
  background jobs and vendor tooling. Never handed to request handlers.

On top of RLS, the ORM adds a company filter to every SELECT of tenant tables
(defence in depth: a missing filter in code still cannot leak data, and a
misconfigured database role still gets filtered queries).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from app.core.config import get_settings
from app.db.base import PLATFORM_COMPANY_ID, Base, TenantMixin


@lru_cache
def app_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def system_engine() -> Engine:
    return create_engine(get_settings().database_system_url, pool_pre_ping=True, future=True)


class TenantSession(Session):
    """Session bound to one company. `info['company_id']` is mandatory."""

    @property
    def company_id(self) -> uuid.UUID:
        return self.info["company_id"]


@event.listens_for(TenantSession, "after_begin")
def _set_rls_context(session: Session, transaction, connection) -> None:
    company_id = session.info.get("company_id")
    connection.execute(text("SELECT set_config('app.company_id', :cid, true)"),
                       {"cid": str(company_id) if company_id else ""})


@event.listens_for(TenantSession, "do_orm_execute")
def _tenant_filter(state) -> None:
    if not state.is_select or state.execution_options.get("skip_tenant_filter"):
        return
    company_id = state.session.info.get("company_id")
    visible = [company_id, PLATFORM_COMPANY_ID]
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not issubclass(cls, TenantMixin) or not hasattr(cls, "__table__"):
            continue
        # plain expressions, not lambdas: SQLAlchemy analyses a lambda's bytecode, which the compiled
        # (Nuitka) server does not have
        if getattr(cls, "__tenancy__", "tenant") == "library":
            criteria = cls.company_id.in_(visible)
        else:
            criteria = cls.company_id == company_id
        state.statement = state.statement.options(with_loader_criteria(cls, criteria, include_aliases=True))


@event.listens_for(TenantSession, "before_flush")
def _stamp_company(session: Session, flush_context, instances) -> None:
    company_id = session.info.get("company_id")
    user_id = session.info.get("user_id")
    for obj in session.new:
        if isinstance(obj, TenantMixin) and getattr(obj, "company_id", None) is None:
            obj.company_id = company_id
        if hasattr(obj, "created_by") and obj.created_by is None:
            obj.created_by = user_id
    for obj in session.dirty:
        if hasattr(obj, "updated_by"):
            obj.updated_by = user_id


@lru_cache
def _tenant_factory() -> sessionmaker:
    return sessionmaker(bind=app_engine(), class_=TenantSession, expire_on_commit=False)


@lru_cache
def _system_factory() -> sessionmaker:
    return sessionmaker(bind=system_engine(), expire_on_commit=False)


def tenant_session(company_id: uuid.UUID, user_id: uuid.UUID | None = None) -> TenantSession:
    session = _tenant_factory()()
    session.info["company_id"] = company_id
    session.info["user_id"] = user_id
    return session


def system_session() -> Session:
    return _system_factory()()


def reset_engines() -> None:
    """Used by tests after changing settings."""
    for fn in (app_engine, system_engine, _tenant_factory, _system_factory):
        fn.cache_clear()


def iter_system_session() -> Iterator[Session]:
    session = system_session()
    try:
        yield session
    finally:
        session.close()
