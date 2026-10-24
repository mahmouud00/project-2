import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.vendor_admin.__main__ import build_license  # noqa: E402

from app.core.config import get_settings
from app.licensing import provider as prov
from app.licensing.signing import generate_keypair, load_private_key, load_public_key, set_vendor_public_key, sign_document

FP = "test-fingerprint-0001"


@pytest.fixture
def vendor_key(monkeypatch):
    priv, pub = generate_keypair()
    set_vendor_public_key(load_public_key(pub))
    monkeypatch.setattr(prov, "machine_fingerprint", lambda: FP)
    import app.modules.system.router as sysrouter
    monkeypatch.setattr(sysrouter, "machine_fingerprint", lambda: FP)
    yield load_private_key(priv)
    set_vendor_public_key(None)


@pytest.fixture
def offline_provider():
    p = prov.OfflineFileLicenseProvider()
    prov.set_license_provider(p)
    path = get_settings().license_file
    path.unlink(missing_ok=True)
    yield p
    path.unlink(missing_ok=True)


def _write(key, **kw):
    defaults = dict(company_code="X", company_name="X", fingerprint=FP, modules=["core", "manufacturing", "mfg.upvc"],
                    max_devices=2)
    defaults.update(kw)
    doc = sign_document(key, build_license(**defaults))
    get_settings().license_file.write_text(json.dumps(doc), encoding="utf-8")
    return doc


def _login(client, tenant, device):
    return client.post("/api/v1/auth/login", json={"company_code": tenant.code, "username": "admin",
                                                   "password": tenant.admin_password, "device_key": device})


def test_missing_license_blocks_login(vendor_key, offline_provider, tenant_a, client):
    r = _login(client, tenant_a, "dev-missing-1")
    assert r.status_code == 402 and r.json()["error"]["code"] == "LICENSE_INVALID"


def test_valid_license_and_device_limit(vendor_key, offline_provider, tenant_a, client):
    _write(vendor_key, max_devices=2)
    assert _login(client, tenant_a, "dev-a-0001").status_code == 200
    assert _login(client, tenant_a, "dev-a-0002").status_code == 200
    assert _login(client, tenant_a, "dev-a-0001").status_code == 200  # known device is fine
    r = _login(client, tenant_a, "dev-a-0003")
    assert r.status_code == 402 and r.json()["error"]["code"] == "LICENSE_DEVICE_LIMIT"


def test_tampered_license_rejected(vendor_key, offline_provider, tenant_a, client):
    doc = _write(vendor_key, max_devices=1)
    doc["payload"]["max_devices"] = 1000
    get_settings().license_file.write_text(json.dumps(doc), encoding="utf-8")
    offline_provider.invalidate()
    ent = offline_provider.entitlements(None, tenant_a.id)
    assert ent.status == "invalid" and ent.reason == "bad_signature"


def test_other_machine_rejected(vendor_key, offline_provider, tenant_a):
    _write(vendor_key, fingerprint="another-machine")
    ent = offline_provider.entitlements(None, tenant_a.id)
    assert ent.status == "invalid" and ent.reason == "machine_mismatch"


def test_grace_then_read_only(vendor_key, offline_provider, tenant_a, client):
    past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _write(vendor_key, expires=past, grace_days=7, max_devices=5)
    assert offline_provider.entitlements(None, tenant_a.id).status == "grace"
    h = {"Authorization": f"Bearer {_login(client, tenant_a, 'dev-g-0001').json()['access_token']}"}
    assert client.post("/api/v1/branches", headers=h, json={"code": "G1", "name": "g"}).status_code == 201

    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    _write(vendor_key, expires=long_ago, grace_days=7, max_devices=5)
    offline_provider.invalidate()
    assert client.get("/api/v1/branches", headers=h).status_code == 200          # read still allowed
    r = client.post("/api/v1/branches", headers=h, json={"code": "G2", "name": "g"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "LICENSE_READ_ONLY"


def test_upload_license_endpoint(vendor_key, offline_provider, tenant_a, client):
    _write(vendor_key, max_devices=5)
    h = {"Authorization": f"Bearer {_login(client, tenant_a, 'dev-u-0001').json()['access_token']}"}
    status = client.get("/api/v1/system/license", headers=h).json()
    assert status["status"] == "valid" and status["machine_fingerprint"] == FP
    new_doc = sign_document(vendor_key, build_license(company_code="X", company_name="X", fingerprint=FP,
                                                      modules=["core"], max_devices=9))
    r = client.post("/api/v1/system/license", headers=h,
                    files={"file": ("lic.json", json.dumps(new_doc).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["max_devices"] == 9
    bad = dict(new_doc, signature=new_doc["signature"][:-4] + "AAAA")
    r = client.post("/api/v1/system/license", headers=h,
                    files={"file": ("lic.json", json.dumps(bad).encode(), "application/json")})
    assert r.status_code == 422


def test_module_gate(vendor_key, offline_provider, tenant_a):
    from app.core.errors import LicenseError
    from app.licensing.service import require_module

    _write(vendor_key, modules=["core", "manufacturing", "mfg.upvc"])
    require_module(None, tenant_a.id, "mfg.upvc")
    with pytest.raises(LicenseError):
        require_module(None, tenant_a.id, "mfg.aluminum")


def test_online_subscription(tenant_a, client):
    from app.db.session import system_session
    from app.licensing.models import Subscription

    prov.set_license_provider(prov.OnlineSubscriptionProvider())
    r = _login(client, tenant_a, "dev-o-0001")
    assert r.status_code == 402  # no subscription
    now = datetime.now(timezone.utc)
    with system_session() as db:
        db.add(Subscription(company_id=tenant_a.id, modules=["core"], max_users=1, max_branches=1, max_devices=3,
                            starts_at=now, expires_at=now + timedelta(days=30)))
        db.commit()
    h = {"Authorization": f"Bearer {_login(client, tenant_a, 'dev-o-0001').json()['access_token']}"}
    roles = client.get("/api/v1/roles", headers=h).json()
    r = client.post("/api/v1/users", headers=h, json={"username": "u2", "password": "user-pass-123",
                                                      "full_name": "u", "assignments": [{"role_id": roles[0]["id"]}]})
    assert r.status_code == 402 and r.json()["error"]["code"] == "LICENSE_USER_LIMIT"
    r = client.post("/api/v1/branches", headers=h, json={"code": "B2", "name": "b"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "LICENSE_BRANCH_LIMIT"
    assert client.get("/api/v1/system/license", headers=h).json()["modules"] == ["core"]


def test_vendor_cli_keygen_issue_show(tmp_path, capsys):
    from tools.vendor_admin.__main__ import main

    priv, pub = tmp_path / "priv.pem", tmp_path / "pub.pem"
    main(["keygen", "--out", str(priv), "--install-public", str(pub)])
    out = tmp_path / "lic.json"
    main(["issue-license", "--key", str(priv), "--company-code", "ACME", "--company-name", "Acme",
          "--fingerprint", FP, "--modules", "mfg.upvc", "--max-devices", "3", "--expires", "2030-01-01",
          "--out", str(out)])
    doc = json.loads(out.read_text())
    assert doc["payload"]["modules"] == ["core", "mfg.upvc", "manufacturing"]
    set_vendor_public_key(load_public_key(pub.read_bytes()))
    try:
        assert prov.evaluate_license_document(doc, FP).status == "valid"
    finally:
        set_vendor_public_key(None)
