"""Update packages: success, failed migration, failed start, tampering, downgrade."""
import json
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.licensing.signing import generate_keypair, load_private_key, load_public_key, set_vendor_public_key
from app.ops.updater import ServiceController, UpdateError, apply_update, build_package, read_current
from tests.conftest import ADMIN_URL

BACKEND = Path(__file__).resolve().parents[1]
UPDATE_DB = "mytech_test_update"

BROKEN = '''
from alembic import op
revision = "9999"
down_revision = "{down}"
branch_labels = None
depends_on = None
def upgrade():
    op.execute("UPDATE companies SET name = 'half-migrated'")
    raise RuntimeError("boom")
def downgrade():
    pass
'''

DATA_MIGRATION = '''
from alembic import op
revision = "9998"
down_revision = "{down}"
branch_labels = None
depends_on = None
def upgrade():
    op.execute("UPDATE companies SET name = name || ' (migrated)'")
def downgrade():
    pass
'''


@pytest.fixture
def key():
    priv, pub = generate_keypair()
    set_vendor_public_key(load_public_key(pub))
    yield load_private_key(priv)
    set_vendor_public_key(None)


@pytest.fixture
def install(tmp_path, monkeypatch):
    """A fresh installation at the current revision with one company."""
    from app.cli import migrate
    from app.ops.backup import current_revision

    s = get_settings()
    owner = make_url(s.database_owner_url)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d"), {"d": UPDATE_DB})
        c.execute(text(f'DROP DATABASE IF EXISTS "{UPDATE_DB}"'))
        c.execute(text(f'CREATE DATABASE "{UPDATE_DB}" OWNER "{owner.username}"'))
    admin.dispose()
    db_admin = create_engine(ADMIN_URL.rsplit("/", 1)[0] + "/" + UPDATE_DB, isolation_level="AUTOCOMMIT")
    with db_admin.connect() as c:
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{owner.username}"'))
    db_admin.dispose()
    url = owner.set(database=UPDATE_DB).render_as_string(hide_password=False)
    migrate(url=url)
    monkeypatch.setenv("DATABASE_OWNER_URL", url)  # child migration process uses the update DB
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'UPD', 'Update Co', true, '{}', 1)"), {"i": uuid.uuid4()})
    engine.dispose()
    root = tmp_path / "MYTech"
    (root / "config").mkdir(parents=True)
    (root / "app" / "0.1.0").mkdir(parents=True)
    (root / "current.json").write_text(json.dumps({"version": "0.1.0", "path": "app/0.1.0"}))
    return {"root": root, "url": url, "revision": current_revision(url)}


def _source(tmp_path, version, extra_migration=None):
    src = tmp_path / f"src-{version}"
    shutil.copytree(BACKEND / "app", src / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(BACKEND / "migrations", src / "migrations", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(BACKEND / "alembic.ini", src / "alembic.ini")
    (src / "VERSION").write_text(version)
    if extra_migration:
        name, body = extra_migration
        (src / "migrations" / "versions" / name).write_text(body)
    return src


def _service(healthy=True):
    calls = []
    return calls, ServiceController(stop=lambda: calls.append("stop"), start=lambda: calls.append("start"),
                                    healthy=lambda v: calls.append(f"health {v}") or healthy)


def _names(url):
    engine = create_engine(url)
    with engine.connect() as c:
        rows = c.execute(text("SELECT name FROM companies ORDER BY code")).scalars().all()
        rev = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    return rows, rev


def test_successful_update_keeps_data(install, key, tmp_path):
    pkg = build_package(_source(tmp_path, "0.2.0", ("9998_data.py", DATA_MIGRATION.format(down=install["revision"]))),
                        "0.2.0", key, min_from_version="0.1.0")
    calls, svc = _service()
    result = apply_update(install["root"], pkg, svc, db_url=install["url"])
    assert result["to"] == "0.2.0" and calls == ["stop", "start", "health 0.2.0"]
    cur = read_current(install["root"])
    assert cur["version"] == "0.2.0" and cur["previous"]["version"] == "0.1.0"
    assert (install["root"] / "app" / "0.2.0" / "app" / "main.py").exists()
    names, rev = _names(install["url"])
    assert names == ["Update Co (migrated)"] and rev == "9998"
    assert (install["root"] / "backups").glob("*pre-update-0.2.0.dump")


def test_failed_migration_rolls_back(install, key, tmp_path):
    pkg = build_package(_source(tmp_path, "0.3.0", ("9999_broken.py", BROKEN.format(down=install["revision"]))),
                        "0.3.0", key)
    calls, svc = _service()
    with pytest.raises(UpdateError, match="rolled back"):
        apply_update(install["root"], pkg, svc, db_url=install["url"])
    assert read_current(install["root"])["version"] == "0.1.0"
    assert _names(install["url"]) == (["Update Co"], install["revision"])
    assert calls[-1] == "start"
    assert "rolled back" in (install["root"] / "logs" / "updates.log").read_text()


def test_failed_start_restores_migrated_data(install, key, tmp_path):
    pkg = build_package(_source(tmp_path, "0.4.0", ("9998_data.py", DATA_MIGRATION.format(down=install["revision"]))),
                        "0.4.0", key)
    calls, svc = _service(healthy=False)
    with pytest.raises(UpdateError):
        apply_update(install["root"], pkg, svc, db_url=install["url"])
    # the data migration had run; the restore brings back the exact old data and revision
    assert _names(install["url"]) == (["Update Co"], install["revision"])
    assert read_current(install["root"])["version"] == "0.1.0"


def test_rejects_tampered_old_or_unsigned(install, key, tmp_path):
    import io
    import zipfile

    pkg = build_package(_source(tmp_path, "0.5.0"), "0.5.0", key)
    z = zipfile.ZipFile(io.BytesIO(pkg))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        for n in z.namelist():
            w.writestr(n, z.read(n) + (b"#evil" if n == "payload/app/main.py" else b""))
    _, svc = _service()
    with pytest.raises(UpdateError, match="corrupted"):
        apply_update(install["root"], out.getvalue(), svc, db_url=install["url"])
    with pytest.raises(UpdateError, match="not newer"):
        apply_update(install["root"], build_package(_source(tmp_path, "0.0.9"), "0.0.9", key), svc,
                     db_url=install["url"])
    with pytest.raises(UpdateError, match="first"):
        apply_update(install["root"], build_package(_source(tmp_path, "0.6.0"), "0.6.0", key,
                                                    min_from_version="0.5.0"), svc, db_url=install["url"])
    other_priv, _ = generate_keypair()
    with pytest.raises(UpdateError, match="signature"):
        apply_update(install["root"], build_package(_source(tmp_path, "0.7.0"), "0.7.0",
                                                    load_private_key(other_priv)), svc, db_url=install["url"])
