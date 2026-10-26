"""How far a work order is: each stage has a planned duration (company settings, in days). The percentage
counts the finished stages plus the time spent in the current one (up to its duration), out of the total."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.base import utcnow
from app.modules.production.models import STAGES, WorkOrder, WorkOrderStageLog

DAY = Decimal(86400)


def stage_entered(db, wo_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, datetime]]:
    """When each order last entered each stage."""
    out: dict[uuid.UUID, dict[str, datetime]] = {}
    if not wo_ids:
        return out
    rows = db.execute(select(WorkOrderStageLog.work_order_id, WorkOrderStageLog.to_stage, func.max(WorkOrderStageLog.at))
                      .where(WorkOrderStageLog.work_order_id.in_(wo_ids))
                      .group_by(WorkOrderStageLog.work_order_id, WorkOrderStageLog.to_stage))
    for wo_id, stage, at in rows:
        out.setdefault(wo_id, {})[stage] = at
    return out


def progress(wo: WorkOrder, entered: dict[str, datetime], durations: dict[str, Decimal],
             now: datetime | None = None) -> dict:
    now = now or utcnow()
    if wo.stage == "cancelled":
        return {"progress_pct": None, "stage_due_at": None, "expected_delivery": None, "late": False}
    if wo.stage == "delivered":
        return {"progress_pct": 100, "stage_due_at": None, "expected_delivery": None, "late": False}
    working = STAGES[:-1]                       # every stage before delivery has a duration
    days = {s: Decimal(durations.get(s, 0)) for s in working}
    index = working.index(wo.stage)
    since = entered.get(wo.stage) or wo.created_at
    spent = Decimal(max((now - since).total_seconds(), 0)) / DAY
    current = days[wo.stage]
    stage_due = since + timedelta(days=float(current))
    remaining_after = sum((days[s] for s in working[index + 1:]), Decimal(0))
    expected = max(stage_due, now) + timedelta(days=float(remaining_after))
    total = sum(days.values(), Decimal(0))
    if total > 0:
        done = sum((days[s] for s in working[:index]), Decimal(0)) + min(spent, current)
        pct = int(done * 100 / total)
    else:                                       # no durations set: by stage count
        pct = int(Decimal(index) * 100 / len(working))
    return {"progress_pct": min(pct, 99), "stage_due_at": stage_due, "expected_delivery": expected.date(),
            "late": current > 0 and now > stage_due}
