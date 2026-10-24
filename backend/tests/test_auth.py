def test_login_refresh_rotation_and_reuse(tenant_a, client):
    tokens = tenant_a.login()
    assert tokens["must_change_password"] is True
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "admin"

    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    new = r1.json()
    # reusing the old refresh token = theft signal -> whole family revoked
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "TOKEN_REUSED"
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new["refresh_token"]})
    assert r3.status_code == 401


def test_wrong_password_and_lockout(tenant_a, client):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"company_code": tenant_a.code, "username": "admin",
                                                    "password": "wrong-pass", "device_key": "dev-xx-1"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"company_code": tenant_a.code, "username": "admin",
                                                "password": tenant_a.admin_password, "device_key": "dev-xx-1"})
    assert r.status_code == 423 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_logout_revokes(tenant_a, client):
    tokens = tenant_a.login()
    assert client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_bad_token_rejected(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


def test_change_password(tenant_a, client):
    h = tenant_a.h
    r = client.post("/api/v1/auth/change-password", headers=h,
                    json={"current_password": tenant_a.admin_password, "new_password": "new-pass-456"})
    assert r.status_code == 204
    assert tenant_a.login(password="new-pass-456")["must_change_password"] is False


def test_old_client_version_rejected(client):
    r = client.get("/api/v1/system/info", headers={"X-Client-Version": "0.0.1"})
    assert r.status_code == 426 and r.json()["error"]["code"] == "CLIENT_UPDATE_REQUIRED"
    r = client.get("/api/v1/system/info", headers={"X-Client-Version": "9.0.0"})
    assert r.status_code == 200 and r.headers["X-Server-Version"]
