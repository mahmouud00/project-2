from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Record(ORMModel):
    id: uuid.UUID
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams:
    def __init__(self, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        self.limit, self.offset = limit, offset


def paginate(db: Session, stmt: Select, params: PageParams, schema) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(params.limit).offset(params.offset)).all()
    return {"items": [schema.model_validate(r) for r in rows], "total": total,
            "limit": params.limit, "offset": params.offset}


class VersionedUpdate(BaseModel):
    """Every update must carry the version the client read (optimistic locking)."""
    version: int


class DeleteResult(BaseModel):
    """What a delete did: "scheduled" (erased after 30 days, see `deletions`), "deleted", or "deactivated" when
    history still points to the record."""
    result: str
    request_id: uuid.UUID | None = None
    due_at: datetime | None = None
