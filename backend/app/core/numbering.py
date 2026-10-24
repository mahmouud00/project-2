"""Gap-free document numbers per company (row-locked counter)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session


def next_number(db: Session, kind: str, prefix: str, branch_code: str | None = None) -> str:
    from app.modules.sales.models import DocumentSequence

    year = date.today().year
    key = f"{kind}:{branch_code or '*'}:{year}"
    seq = db.scalar(select(DocumentSequence).where(DocumentSequence.key == key).with_for_update())
    if seq is None:
        seq = DocumentSequence(key=key, next_value=1)
        db.add(seq)
        db.flush()
    value = seq.next_value
    seq.next_value = value + 1
    parts = [prefix] + ([branch_code] if branch_code else []) + [str(year), f"{value:05d}"]
    return "-".join(parts)
