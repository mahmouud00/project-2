import json
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from tests.conftest import ADMIN_URL

BACKUP_DB = "mytech_test_backup"


@pytest.fixture(scope="module")
def backup_db_url():
    from app.cli import migrate

    s = get_settings()
    owner = make_url(s.database_owner_url)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{BACKUP_DB}"'))
        c.execute(text(f'CREATE DATABASE "{BACKUP_DB}" OWNER "{owner.username}"'))
    admin.dispose()
    db_admin = create_engine(ADMIN_URL.rsplit("/", 1)[0] + "/" + BACKUP_DB, isolation_level="AUTOCOMMIT")
    with db_admin.connect() as c:
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{owner.username}"'))
    db_admin.dispose()
    url = owner.set(database=BACKUP_DB).render_as_string(hide_password=False)
    migrate(url=url)
    return url


def test_backup_restore_roundtrip(backup_db_url, tmp_path):
    from app.ops.backup import BackupError, list_backups, restore, run_backup

    engine = create_engine(backup_db_url)
    cid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'BK', 'Backup Co', true, '{}', 1)"), {"i": cid})
    path = run_backup("manual", dest=tmp_path, url=backup_db_url)
    assert list_backups(tmp_path)[0]["file"] == path.name
    with engine.begin() as c:
        c.execute(text("UPDATE companies SET name = 'changed after backup' WHERE id = :i"), {"i": cid})
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'NEW', 'new', true, '{}', 1)"), {"i": uuid.uuid4()})
    engine.dispose()
    restore(path, safety_backup=False, url=backup_db_url)
    engine = create_engine(backup_db_url)
    with engine.connect() as c:
        rows = c.execute(text("SELECT code, name FROM companies ORDER BY code")).all()
        rls = c.execute(text("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'companies'")).scalar()
    engine.dispose()
    assert rows == [("BK", "Backup Co")] and rls is True
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(BackupError):
        restore(path, safety_backup=False, url=backup_db_url)


def test_retention(backup_db_url, tmp_path):
    from app.ops.backup import list_backups, run_backup

    s = get_settings()
    old_keep, s.backup_keep = s.backup_keep, 2
    try:
        for _ in range(4):
            run_backup("daily", dest=tmp_path, url=backup_db_url)
        assert len(list(tmp_path.glob("*_daily.dump"))) == 2
        assert len(list_backups(tmp_path)) == 2
    finally:
        s.backup_keep = old_keep


def test_backup_endpoint(tenant_a, client):
    r = client.post("/api/v1/system/backups", headers=tenant_a.h)
    assert r.status_code == 201, r.text
    listing = client.get("/api/v1/system/backups", headers=tenant_a.h).json()
    assert listing["last_status"]["ok"] is True and listing["backups"]


def test_live_events_reach_only_same_company(app, tenant_a, tenant_b):
    from fastapi.testclient import TestClient

    s = get_settings()
    s.discovery_enabled = False
    try:
        with TestClient(app) as c:
            ta = tenant_a.login(device_key="ws-dev-a")["access_token"]
            tb = tenant_b.login(device_key="ws-dev-b")["access_token"]
            with c.websocket_connect(f"/api/v1/system/events?token={ta}") as ws_a, \
                    c.websocket_connect(f"/api/v1/system/events?token={tb}") as ws_b:
                time.sleep(0.5)  # listener subscribed
                r = c.post("/api/v1/branches", headers={"Authorization": f"Bearer {ta}"},
                           json={"code": "LIVE", "name": "live"})
                assert r.status_code == 201
                event = ws_a.receive_json()
                assert event["type"] == "change" and event["entity"] == "branches" and event["id"] == r.json()["id"]
                assert "cid" not in event
                c.post("/api/v1/branches", headers={"Authorization": f"Bearer {tb}"}, json={"code": "LB", "name": "b"})
                assert ws_b.receive_json()["entity"] == "branches"
            with pytest.raises(Exception):
                with c.websocket_connect("/api/v1/system/events?token=bad") as ws:
                    ws.receive_json()
    finally:
        s.discovery_enabled = True


def test_udp_discovery():
    from app.ops.discovery import UdpResponder, discover

    responder = UdpResponder(port=0)
    responder.start()
    try:
        found = discover(timeout=1.0, port=responder.port, target="127.0.0.1")
    finally:
        responder.stop()
    assert found and found[0]["product"] == "MYTech Solutions" and found[0]["api"] == "/api/v1"


def test_cli_version_fingerprint_and_admin_url(capsys, monkeypatch):
    from app.cli import main
    from app.core.config import read_version

    main(["version"])
    assert capsys.readouterr().out.strip() == read_version() != "0.0.0"
    main(["fingerprint"])
    assert len(capsys.readouterr().out.strip()) >= 32
    monkeypatch.delenv("MYTECH_ADMIN_URL", raising=False)
    with pytest.raises(SystemExit):           # the superuser URL is required (flag or environment)
        main(["init-db"])


def test_desktop_program_origin_allowed_by_cors(client):
    ok = client.options("/api/v1/system/info", headers={"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://tauri.localhost"
    bad = client.options("/api/v1/system/info", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_cli_recovers_utf8_arguments():
    from app.cli import _utf8_args

    raw = "مصنع".encode("utf-8").decode("ascii", "surrogateescape")   # how a C-locale shell hands it over
    assert raw != "مصنع"
    assert _utf8_args([raw, "ACME"]) == ["مصنع", "ACME"]


def test_move_to_another_server(backup_db_url, tmp_path, monkeypatch):
    """export (database + pictures) on the factory PC, import on the cloud server: everything comes back."""
    from app.ops.backup import export_bundle, import_bundle

    s = get_settings()
    old_media, new_media = tmp_path / "old_media", tmp_path / "new_media"
    (old_media / "ab").mkdir(parents=True)
    (old_media / "ab" / "abcdef").write_bytes(b"\x89PNG model picture")
    monkeypatch.setattr(s, "media_dir", old_media)
    monkeypatch.setattr(s, "backup_dir", tmp_path / "backups")
    engine = create_engine(backup_db_url)
    with engine.begin() as c:
        c.execute(text("DELETE FROM companies WHERE code = 'MOVE'"))
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'MOVE', 'Moving Co', true, '{}', 1)"), {"i": uuid.uuid4()})
    bundle = export_bundle(tmp_path / "move.zip", url=backup_db_url)
    with engine.begin() as c:
        c.execute(text("DELETE FROM companies WHERE code = 'MOVE'"))
    engine.dispose()
    monkeypatch.setattr(s, "media_dir", new_media)          # the new server: empty picture folder
    meta = import_bundle(bundle, url=backup_db_url)
    assert meta["pictures"] == 1 and (new_media / "ab" / "abcdef").read_bytes() == b"\x89PNG model picture"
    engine = create_engine(backup_db_url)
    with engine.connect() as c:
        assert c.execute(text("SELECT name FROM companies WHERE code = 'MOVE'")).scalar() == "Moving Co"
    engine.dispose()


def test_backup_copies_pictures(backup_db_url, tmp_path, monkeypatch):
    from app.ops.backup import run_backup

    media = tmp_path / "media"
    (media / "cd").mkdir(parents=True)
    (media / "cd" / "cdef").write_bytes(b"logo")
    monkeypatch.setattr(get_settings(), "media_dir", media)
    run_backup("manual", dest=tmp_path / "b", url=backup_db_url)
    assert (tmp_path / "b" / "media" / "cd" / "cdef").read_bytes() == b"logo"
