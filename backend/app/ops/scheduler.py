"""Background jobs: daily backup. A PostgreSQL advisory lock makes sure only
one API worker runs a job even when several workers are started."""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.core.config import get_settings

log = logging.getLogger("mytech.scheduler")
BACKUP_LOCK = 7_300_001


def _backup_job() -> None:
    from app.db.session import system_engine
    from app.ops.backup import BackupError, run_backup

    with system_engine().connect() as c:
        if not c.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": BACKUP_LOCK}).scalar():
            return
        try:
            run_backup("daily")
        except BackupError as e:
            log.error("daily backup failed: %s", e)
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": BACKUP_LOCK})


def _purge_locations_job() -> None:
    """Technician GPS points are personal data: erased after LOCATION_RETENTION_DAYS (all companies)."""
    from app.db.session import system_session
    from app.modules.field.router import purge_old_locations

    db = system_session()
    try:
        n = purge_old_locations(db, get_settings().location_retention_days)
        db.commit()
        if n:
            log.info("erased %d old technician locations", n)
        from app.modules.notifications.router import purge_old_notifications
        purge_old_notifications(db)
        db.commit()
    except Exception as e:
        db.rollback()
        log.error("location purge failed: %s", type(e).__name__)
    finally:
        db.close()


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    s = get_settings()
    sched = BackgroundScheduler(timezone="Africa/Cairo")
    sched.add_job(_backup_job, "cron", hour=s.backup_hour, minute=0, id="daily_backup", coalesce=True,
                  misfire_grace_time=6 * 3600)
    sched.add_job(_purge_locations_job, "cron", hour=3, minute=30, id="purge_locations", coalesce=True,
                  misfire_grace_time=12 * 3600)
    sched.start()
    return sched
