"""Every migration must keep existing data: seed at an old revision, upgrade to head, compare."""
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from tests.conftest import ADMIN_URL

MIG_DB = "mytech_test_migrations"


def test_upgrade_from_old_revision_keeps_data():
    from app.cli import migrate

    s = get_settings()
    owner = make_url(s.database_owner_url)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        c.execute(text(f'CREATE DATABASE "{MIG_DB}" OWNER "{owner.username}"'))
    admin.dispose()
    db_admin = create_engine(ADMIN_URL.rsplit("/", 1)[0] + "/" + MIG_DB, isolation_level="AUTOCOMMIT")
    with db_admin.connect() as c:
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{owner.username}"'))
    db_admin.dispose()
    url = owner.set(database=MIG_DB).render_as_string(hide_password=False)

    migrate(url=url, revision="0001")
    cid, uid = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'OLD', 'Old company', true, '{\"currency\": \"EGP\"}', 3)"), {"i": cid})
        c.execute(text("INSERT INTO users (id, company_id, username, password_hash, full_name, is_active, "
                       "failed_logins, must_change_password, version) VALUES (:u, :c, 'old', 'h', 'Old user', true, "
                       "0, false, 2)"), {"u": uid, "c": cid})
    before = _dump(engine)
    engine.dispose()

    migrate(url=url, revision="0002")
    engine = create_engine(url)
    with engine.begin() as c:
        sid = uuid.uuid4()
        c.execute(text("INSERT INTO profile_systems (id, company_id, code, name, supplier, material_type, unit, "
                       "rounding_step_mm, rounding_mode, status, description, is_active, version) VALUES "
                       "(:s, :c, 'S', 'Sys', '', 'upvc', 'cm', 0, 'half_up', 'approved', '', true, 1)"),
                  {"s": sid, "c": cid})
    before2 = _dump(engine)
    engine.dispose()

    migrate(url=url)  # head
    engine = create_engine(url)
    after = _dump(engine)
    engine.dispose()
    for table, rows in {**before, **before2}.items():
        assert set(after[table]) == set(rows), f"rows lost or added in {table}"
        for row_id, old in rows.items():
            new = after[table][row_id]
            # new columns may appear; every old value must be unchanged
            assert {k: new.get(k) for k in old} == old, f"data changed in {table} {row_id}"


def _dump(engine) -> dict:
    import json

    out = {}
    with engine.connect() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                                "AND tablename <> 'alembic_version'")).scalars().all()
        for t in tables:
            rows = [json.loads(r) for r in c.execute(text(f'SELECT row_to_json(x)::text FROM "{t}" x')).scalars()]
            if rows:
                out[t] = {r["id"]: r for r in rows}
    return out
