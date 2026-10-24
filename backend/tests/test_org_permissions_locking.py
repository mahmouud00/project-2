def _make_user(tenant, client, username, role_code, branch_id=None):
    roles = {r["code"]: r for r in client.get("/api/v1/roles", headers=tenant.h).json()}
    r = client.post("/api/v1/users", headers=tenant.h, json={
        "username": username, "password": "user-pass-123", "full_name": "Test User",
        "assignments": [{"role_id": roles[role_code]["id"], "branch_id": branch_id}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_role_permissions_enforced(tenant_a, client):
    _make_user(tenant_a, client, "sales1", "sales")
    h = tenant_a.headers("sales1", "user-pass-123")
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.post("/api/v1/branches", headers=h, json={"code": "B2", "name": "x"}).status_code == 403
    assert client.get("/api/v1/branches", headers=h).status_code == 200


def test_branch_scoped_role(tenant_a, client):
    b = client.post("/api/v1/branches", headers=tenant_a.h, json={"code": "B2", "name": "Branch 2"}).json()
    _make_user(tenant_a, client, "wh1", "warehouse", b["id"])
    me = client.get("/api/v1/auth/me", headers=tenant_a.headers("wh1", "user-pass-123")).json()
    assert list(me["grants"]) == [b["id"]]
    assert "inventory.write" in me["grants"][b["id"]]


def test_optimistic_locking(tenant_a, client):
    b = client.post("/api/v1/branches", headers=tenant_a.h, json={"code": "B9", "name": "Old"}).json()
    r1 = client.patch(f"/api/v1/branches/{b['id']}", headers=tenant_a.h, json={"version": b["version"], "name": "A"})
    assert r1.status_code == 200 and r1.json()["version"] == b["version"] + 1
    # second editor still holds the old version -> rejected, first edit kept
    r2 = client.patch(f"/api/v1/branches/{b['id']}", headers=tenant_a.h, json={"version": b["version"], "name": "B"})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "VERSION_CONFLICT"
    assert r2.json()["error"]["details"]["current"]["name"] == "A"


def test_audit_log_records_and_masks_pii(tenant_a, client):
    _make_user(tenant_a, client, "audited", "sales")
    logs = client.get("/api/v1/audit-log?entity=users", headers=tenant_a.h).json()["items"]
    created = [l for l in logs if l["action"] == "create"][0]
    assert created["changes"]["full_name"] == "***"
    assert "password_hash" not in created["changes"]


def test_unknown_permission_rejected(tenant_a, client):
    r = client.post("/api/v1/roles", headers=tenant_a.h, json={"code": "x", "name": "x", "permissions": ["nope"]})
    assert r.status_code == 422
