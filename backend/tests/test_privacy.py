import logging


def test_export_and_erase_customer(tenant_a, tenant_b, client):
    h = tenant_a.h
    branch = client.get("/api/v1/branches", headers=h).json()["items"][0]
    c = client.post("/api/v1/customers", headers=h, json={"name": "منى علي", "phone": "01122334455",
                                                          "national_id": "29001011234567", "address": "الجيزة"}).json()
    client.post("/api/v1/surveys", headers=h, json={"customer_id": c["id"], "branch_id": branch["id"],
                                                    "address": "الجيزة شارع 1"})
    exp = client.get(f"/api/v1/privacy/subjects/customer/{c['id']}/export", headers=h)
    assert exp.status_code == 200
    data = exp.json()
    assert data["personal_data"]["phone"] == "01122334455" and data["surveys"][0]["address"] == "الجيزة شارع 1"
    assert client.get(f"/api/v1/privacy/subjects/customer/{c['id']}/export", headers=tenant_b.h).status_code == 404

    r = client.post(f"/api/v1/privacy/subjects/customer/{c['id']}/erase", headers=h, json={"reason": "طلب العميل"})
    assert r.status_code == 200 and set(r.json()["fields"]) >= {"name", "phone", "national_id", "address"}
    after = client.get(f"/api/v1/customers/{c['id']}", headers=h).json()
    assert after["anonymized"] and after["phone"] is None and after["national_id"] is None
    assert after["name"].startswith("عميل محذوف")
    survey = client.get(f"/api/v1/surveys?customer_id={c['id']}", headers=h).json()["items"][0]
    assert survey["address"] is None
    log = client.get(f"/api/v1/privacy/access-log?subject_id={c['id']}", headers=h).json()["items"]
    assert {"export", "erase", "view", "create"} <= {l["action"] for l in log}
    # audit trail of the erasure does not contain the erased values
    audit = client.get(f"/api/v1/audit-log?entity_id={c['id']}", headers=h).json()["items"]
    assert "01122334455" not in str(audit) and "29001011234567" not in str(audit)


def test_logs_never_contain_personal_data(tenant_a, client, caplog):
    from app.core.logging import RedactingFilter, redact

    assert "01012345678" not in redact("calling customer 01012345678 now")
    assert "29001011234567" not in redact("id 29001011234567")
    assert "secret-pass" not in redact('{"password": "secret-pass"}')
    assert "abc.def" not in redact("Authorization: Bearer abc.def")
    record = logging.LogRecord("x", logging.INFO, "f", 1, "phone %s", ("01099998888",), None)
    RedactingFilter().filter(record)
    assert "01099998888" not in record.getMessage()


def test_privacy_requires_permission(tenant_a, client):
    roles = {r["code"]: r for r in client.get("/api/v1/roles", headers=tenant_a.h).json()}
    client.post("/api/v1/users", headers=tenant_a.h, json={"username": "pv", "password": "user-pass-123",
                                                          "full_name": "p", "assignments": [{"role_id": roles["sales"]["id"]}]})
    h = tenant_a.headers("pv", "user-pass-123")
    assert client.get("/api/v1/privacy/access-log", headers=h).status_code == 403
