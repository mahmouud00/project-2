"""Audit log + optimistic-locking helpers used by every service."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.errors import VersionConflict

_SKIP = {"password_hash", "updated_at", "created_at", "version"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def snapshot(obj: Any) -> dict:
    pii = set(getattr(obj, "__pii__", ()))
    out = {}
    for attr in inspect(obj).mapper.column_attrs:
        key = attr.key
        if key in _SKIP:
            continue
        value = getattr(obj, key)
        out[key] = "***" if (key in pii and value not in (None, "")) else _jsonable(value)
    return out


def diff(before: dict | None, after: dict | None) -> dict:
    before, after = before or {}, after or {}
    keys = set(before) | set(after)
    return {k: {"old": before.get(k), "new": after.get(k)} for k in sorted(keys) if before.get(k) != after.get(k)}


def audit(db: Session, obj: Any, action: str, before: dict | None = None, note: str | None = None) -> None:
    from app.modules.org.models import AuditLog

    after = None if action == "delete" else snapshot(obj)
    changes = diff(before, after) if action == "update" else (after or before or {})
    if action == "update" and not changes:
        return
    db.add(AuditLog(
        company_id=db.info.get("company_id") or getattr(obj, "company_id", None),
        user_id=db.info.get("user_id"), device_id=db.info.get("device_id"),
        entity=obj.__tablename__, entity_id=str(getattr(obj, "id", "")), action=action,
        changes=changes, note=note,
    ))


def check_version(obj: Any, expected: int | None) -> None:
    """The client must send the version it read. Mismatch -> 409 with current state."""
    if expected is None or obj.version != expected:
        raise VersionConflict("Record was modified by someone else",
                              details={"current_version": obj.version, "current": snapshot(obj)})


def apply_changes(obj: Any, data: dict) -> None:
    for key, value in data.items():
        setattr(obj, key, value)
