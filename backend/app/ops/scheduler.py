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
            path = run_backup("daily")
        except BackupError as e:
            log.error("daily backup failed: %s", e)
        else:
            from app.ops.offsite import OffsiteError, copy_backup
            try:
                copy_backup(path)                     # the encrypted copy outside the factory, when set
            except OffsiteError:
                pass                                  # recorded; the admin hears about it from the check below
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": BACKUP_LOCK})


def _backup_watch_job() -> None:
    """Every morning: tell whoever manages the system when backups stopped (or the outside copy fails)."""
    from app.ops.offsite import problems

    if get_settings().is_online:              # online: backups are MYTech's job, watched there
        return
    try:
        found = problems()
        if found:
            notify_admins("النسخ الاحتياطي محتاج مراجعة", " · ".join(found), "system")
    except Exception as e:
        log.error("backup check failed: %s", type(e).__name__)


def notify_admins(title: str, body: str, link: str) -> int:
    """A notification to everyone with system.manage in every company of this server (offline: the factory)."""
    from sqlalchemy import select

    from app.db.base import PLATFORM_COMPANY_ID
    from app.db.session import system_session
    from app.modules.notifications.models import Notification
    from app.modules.notifications.router import recipients
    from app.modules.org.models import Company, User

    n = 0
    with system_session() as db:
        for company in db.scalars(select(Company).where(Company.is_active, Company.id != PLATFORM_COMPANY_ID)):
            users = {u for u in recipients(db, "system.manage", None)
                     if db.scalar(select(User.company_id).where(User.id == u)) == company.id}
            for uid in users:
                db.add(Notification(company_id=company.id, user_id=uid, category="system", title=title[:200],
                                    body=body, link=link))
                n += 1
        db.commit()
    return n


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


def _deletions_job() -> None:
    """Erase what waited its 30 days (طلبات الحذف)."""
    from app.modules.deletions.router import run_due_deletions

    try:
        n = run_due_deletions()
        if n:
            log.info("erased %d deleted records after their 30 days", n)
    except Exception as e:
        log.error("deletions job failed: %s", type(e).__name__)


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    s = get_settings()
    sched = BackgroundScheduler(timezone="Africa/Cairo")
    sched.add_job(_backup_job, "cron", hour=s.backup_hour, minute=0, id="daily_backup", coalesce=True,
                  misfire_grace_time=6 * 3600)
    sched.add_job(_purge_locations_job, "cron", hour=3, minute=30, id="purge_locations", coalesce=True,
                  misfire_grace_time=12 * 3600)
    sched.add_job(_backup_watch_job, "cron", hour=10, minute=7, id="backup_watch", coalesce=True,
                  misfire_grace_time=12 * 3600)
    sched.add_job(_deletions_job, "interval", hours=1, id="due_deletions", coalesce=True)
    sched.start()
    return sched
