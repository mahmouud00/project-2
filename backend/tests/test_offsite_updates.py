"""The encrypted backup copy outside the factory, the warning when backups stop, and updates from inside the program."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.licensing.signing import generate_keypair, load_private_key, load_public_key, set_vendor_public_key


def test_encryption_round_trip_and_wrong_password(tmp_path, monkeypatch):
    from app.ops import offsite

    monkeypatch.setattr(offsite, "CHUNK", 1000)           # several chunks, the last one short
    for size in (0, 1000, 3500):
        src = tmp_path / f"f{size}.bin"
        src.write_bytes(bytes(range(256)) * (size // 256) + b"x" * (size % 256))
        enc, out = tmp_path / f"f{size}.mtb", tmp_path / f"f{size}.out"
        offsite.encrypt_file(src, enc, "pass-word-1")
        assert src.read_bytes()[:64] not in enc.read_bytes() or size == 0
        offsite.decrypt_file(enc, out, "pass-word-1")
        assert out.read_bytes() == src.read_bytes()
        with pytest.raises(offsite.OffsiteError):
            offsite.decrypt_file(enc, tmp_path / "bad", "another-pass")
    cut = tmp_path / "cut.mtb"                             # a copy that stopped half way is refused
    cut.write_bytes((tmp_path / "f3500.mtb").read_bytes()[:-1100])
    with pytest.raises(offsite.OffsiteError):
        offsite.decrypt_file(cut, tmp_path / "cut.out", "pass-word-1")
    assert not (tmp_path / "cut.out").exists()


def test_offsite_copy_from_the_program(tenant_a, client, tmp_path):
    from app.ops.offsite import decrypt_file, load_config

    h = tenant_a.h
    outside = tmp_path / "Google Drive" / "MYTech"
    r = client.put("/api/v1/system/backups/offsite", headers=h, json={"folder": str(outside), "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OFFSITE_INVALID"
    r = client.put("/api/v1/system/backups/offsite", headers=h, json={"folder": str(outside), "password": "Backup-Pass-1"})
    assert r.status_code == 200 and r.json()["enabled"], r.text
    assert "Backup-Pass-1" not in json.dumps(load_config())   # never kept as written

    media = get_settings().media_dir
    (media / "aa").mkdir(exist_ok=True)
    (media / "aa" / "picture.png").write_bytes(b"png-bytes")
    r = client.post("/api/v1/system/backups", headers=h)
    assert r.status_code == 201 and r.json()["offsite"], r.text
    copy = outside / (r.json()["file"].rsplit(".", 1)[0] + ".mtb")
    assert copy.exists() and (outside / "media" / "aa" / "picture.png.mtb").exists()
    out = tmp_path / "restored.dump"
    decrypt_file(copy, out, "Backup-Pass-1")
    assert out.read_bytes() == (get_settings().backup_dir / r.json()["file"]).read_bytes()

    st = client.get("/api/v1/system/backups/offsite", headers=h).json()
    assert st["last"]["ok"] and st["problems"] == []
    # the folder changes later, the password stays
    r = client.put("/api/v1/system/backups/offsite", headers=h, json={"folder": str(tmp_path / "usb")})
    assert r.status_code == 200 and r.json()["enabled"]
    assert client.put("/api/v1/system/backups/offsite", headers=h, json={"folder": ""}).json()["enabled"] is False


def test_admin_is_told_when_backups_stop(tenant_a, client, monkeypatch):
    from app.ops import offsite, scheduler

    later = datetime.now(timezone.utc) + timedelta(days=3)
    assert any("يوم ونص" in p for p in offsite.problems(later))
    assert offsite.problems() == [] or all("برّه" in p for p in offsite.problems())

    monkeypatch.setattr(offsite, "problems", lambda now=None: ["مفيش نسخة احتياطية اتعملت من أكتر من يوم ونص"])
    scheduler._backup_watch_job()
    inbox = client.get("/api/v1/notifications", headers=tenant_a.h).json()
    assert any(n["title"] == "النسخ الاحتياطي محتاج مراجعة" and n["category"] == "system" for n in inbox["items"])


def test_clients_offered_and_downloaded(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "clients_dir", str(tmp_path))
    assert client.get("/api/v1/system/clients").json() == {"desktop": None, "android": None}
    for name in ("MYTech-Desktop-Setup-0.1.9.exe", "MYTech-Desktop-Setup-0.1.12.exe", "MYTech-Mobile-0.1.12.apk",
                 "notes.txt"):
        (tmp_path / name).write_bytes(name.encode())
    out = client.get("/api/v1/system/clients").json()            # public: an old program asks before signing in
    assert out["desktop"]["version"] == "0.1.12" and out["android"]["version"] == "0.1.12"
    r = client.get("/api/v1/system/clients/desktop")
    assert r.status_code == 200 and r.content == b"MYTech-Desktop-Setup-0.1.12.exe"
    assert client.get("/api/v1/system/clients/other").status_code == 404


def test_server_update_upload_checks_the_package(tenant_a, client, tmp_path, monkeypatch):
    from app.modules.system import updates
    from app.ops.updater import build_package

    priv, pub = generate_keypair()
    set_vendor_public_key(load_public_key(pub))
    try:
        src = tmp_path / "src"
        src.mkdir()
        (src / "VERSION").write_text("99.0.0")
        good = build_package(src, "99.0.0", load_private_key(priv))
        old = build_package(src, "0.0.1", load_private_key(priv))
        h = tenant_a.h
        bad = client.post("/api/v1/system/update", headers=h, files={"file": ("x.mtu", b"not a zip")})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "UPDATE_INVALID"
        r = client.post("/api/v1/system/update", headers=h, files={"file": ("x.mtu", old)})
        assert r.status_code == 409 and r.json()["error"]["code"] == "UPDATE_NOT_NEWER"
        r = client.post("/api/v1/system/update", headers=h, files={"file": ("x.mtu", good)})
        assert r.status_code == 409 and r.json()["error"]["code"] == "UPDATE_UNAVAILABLE"   # not an installed server

        # an installed Windows server: the package is kept and handed to the scheduled task
        root = tmp_path / "MYTech"
        (root / "logs").mkdir(parents=True)
        (root / "current.json").write_text("{}")
        monkeypatch.setenv("MYTECH_ROOT", str(root))
        monkeypatch.setattr(updates, "on_windows", lambda: True)
        started = []
        monkeypatch.setattr(updates, "schedule", lambda r, p: started.append((r, p)))
        r = client.post("/api/v1/system/update", headers=h, files={"file": ("x.mtu", good)})
        assert r.status_code == 202 and r.json()["version"] == "99.0.0", r.text
        assert started and started[0][1].read_bytes() == good
        assert client.get("/api/v1/system/update", headers=h).json()["can_update"] is True
    finally:
        set_vendor_public_key(None)


def test_update_task_script(tmp_path, monkeypatch):
    from app.modules.system import updates

    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(updates.subprocess, "run", lambda cmd, **k: calls.append(cmd) or Done())
    (tmp_path / "updates").mkdir()
    updates.schedule(tmp_path, tmp_path / "updates" / "mytech-9.0.0.mtu")
    script = (tmp_path / "updates" / "run-update.cmd").read_text(encoding="utf-8")
    assert "update.ps1" in script and "mytech-9.0.0.mtu" in script and "schtasks /Delete" in script
    assert calls[0][:2] == ["schtasks", "/Create"] and "SYSTEM" in calls[0] and calls[1][:2] == ["schtasks", "/Run"]
