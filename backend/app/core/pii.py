"""Personal data access log (Law 151/2020): who viewed/changed/exported/erased whose data."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session


def log_pii(db: Session, ctx, subject_type: str, subject_ids: Iterable, action: str, fields: Iterable[str]) -> None:
    from app.modules.org.models import PiiAccessLog

    fields = sorted(set(fields))
    for sid in subject_ids:
        db.add(PiiAccessLog(user_id=ctx.user_id, device_id=ctx.device_id, ip=ctx.ip, subject_type=subject_type,
                            subject_id=str(sid), action=action, fields=fields))
