"""Two-step login with an authenticator app, the company asking it of administrators, and signed-in devices."""
import time

from app.auth import totp


def _login(client, tenant, otp=None, device="test-device-01"):
    return client.post("/api/v1/auth/login", json={"company_code": tenant.code, "username": "admin",
                                                   "password": tenant.admin_password, "device_key": device, "otp": otp})


def _code(secret, shift=0):
    return totp.code_at(secret, int(time.time() // 30) + shift)


def test_two_step_login(tenant_a, client):
    h = tenant_a.h
    setup = client.post("/api/v1/auth/2fa/setup", headers=h).json()
    assert setup["uri"].startswith("otpauth://totp/") and "<svg" in setup["qr_svg"]
    secret = setup["secret"]
    assert client.get("/api/v1/auth/me", headers=h).json()["two_factor_enabled"] is False   # not until a code is confirmed
    assert client.post("/api/v1/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 422
    assert client.post("/api/v1/auth/2fa/enable", headers=h, json={"code": _code(secret, -1)}).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).json()["two_factor_enabled"] is True

    r = _login(client, tenant_a)
    assert r.status_code == 401 and r.json()["error"]["code"] == "OTP_REQUIRED"
    r = _login(client, tenant_a, "123456" if _code(secret) != "123456" else "654321")
    assert r.status_code == 401 and r.json()["error"]["code"] == "OTP_INVALID"
    code = _code(secret)
    assert _login(client, tenant_a, code).status_code == 200
    assert _login(client, tenant_a, code).json()["error"]["code"] == "OTP_INVALID"          # a code works once

    # the secret is not in the audit log
    users = client.get("/api/v1/users", headers=h).json()["items"]
    admin = next(u for u in users if u["username"] == "admin")
    assert admin["two_factor_enabled"] is True
    log = client.get("/api/v1/audit-log", headers=h, params={"entity_id": admin["id"]}).json()["items"]
    assert not any("totp_secret" in e["changes"] for e in log)

    # a lost phone: an administrator (here the same) turns it off; signing in needs no code again
    assert client.post(f"/api/v1/users/{admin['id']}/2fa/reset", headers=h).json()["two_factor_enabled"] is False
    assert _login(client, tenant_a).status_code == 200


def test_company_asks_it_of_administrators(tenant_b, client):
    h = tenant_b.h
    company = client.get("/api/v1/company", headers=h).json()
    r = client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {"two_factor_for_admins": True}})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/auth/me", headers=h).json()["two_factor_required"] is True
    secret = client.post("/api/v1/auth/2fa/setup", headers=h).json()["secret"]
    client.post("/api/v1/auth/2fa/enable", headers=h, json={"code": _code(secret)})
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["two_factor_enabled"] is True and me["two_factor_required"] is False
    r = client.post("/api/v1/auth/2fa/disable", headers=h, json={"password": tenant_b.admin_password, "code": _code(secret, 1)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TWO_FACTOR_REQUIRED"


def test_signed_in_devices_and_signing_one_out(tenant_a, client):
    first = _login(client, tenant_a, device="phone-device-1").json()
    _login(client, tenant_a, device="laptop-device-2")
    h = {"Authorization": f"Bearer {first['access_token']}"}
    sessions = client.get("/api/v1/auth/sessions", headers=h).json()
    assert len(sessions) >= 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert client.post(f"/api/v1/auth/sessions/{other['id']}/revoke", headers=h).status_code == 204
    assert other["id"] not in [s["id"] for s in client.get("/api/v1/auth/sessions", headers=h).json()]
    # the current device keeps working
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 200


def test_signing_in_again_on_a_device_ends_its_earlier_sign_in(tenant_a, client):
    old = _login(client, tenant_a, device="same-device-9").json()
    new = _login(client, tenant_a, device="same-device-9").json()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 200
