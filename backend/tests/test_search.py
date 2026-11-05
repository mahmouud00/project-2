"""البحث الشامل: finds records by number, code or name; only the caller's company, only the sections they may read,
and the personal data it shows is logged."""
from tests.library_helpers import build_library
from tests.test_org_permissions_locking import _make_user


def _search(client, h, q):
    r = client.get("/api/v1/search", headers=h, params={"q": q})
    assert r.status_code == 200, r.text
    return {g["kind"]: g["items"] for g in r.json()["groups"]}


def test_search_finds_records_by_number_code_and_name(platform, tenant_a, client):
    h = tenant_a.h
    lib = build_library(client, platform, code="SRCH-LIB", prefix="SRL-")
    cust = client.post("/api/v1/customers", headers=h, json={"name": "عميل بحث نادر", "phone": "01099887766"}).json()
    branch = client.get("/api/v1/branches", headers=h).json()["items"][0]
    sv = client.post("/api/v1/surveys", headers=h, json={"customer_id": cust["id"], "branch_id": branch["id"]}).json()
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": cust["id"], "branch_id": branch["id"],
                                                         "lines": []}).json()
    found = _search(client, h, "بحث نادر")
    assert [c["id"] for c in found["customers"]] == [cust["id"]] and found["customers"][0]["path"] == f"customers/{cust['id']}"
    assert sv["id"] in [x["id"] for x in found["surveys"]]                       # by the customer's name
    assert found["quotations"][0]["path"] == f"quotations/{q['id']}"
    assert _search(client, h, q["number"])["quotations"][0]["id"] == q["id"]     # by number
    assert _search(client, h, "01099887766")["customers"][0]["id"] == cust["id"]  # by phone
    m = _search(client, h, "SRCH-LIB")
    assert m["systems"][0]["path"] == f"library/{lib['system']['id']}"
    mdl = lib["model"]
    assert client.patch(f"/api/v1/library/models/{mdl['id']}", headers=platform.h,
                        json={"version": mdl["version"], "name": "شباك بحث فريد"}).status_code == 200
    model = _search(client, h, "بحث فريد")["models"]
    assert any(x["path"] == f"library/{lib['system']['id']}/models/{lib['model']['id']}" for x in model)
    # the customer names shown were logged
    log = client.get("/api/v1/privacy/access-log", headers=h, params={"subject_id": cust["id"]})
    assert log.status_code == 200, log.text
    assert any(r["action"] == "search" for r in log.json()["items"])


def test_search_stays_in_the_company_and_the_permissions(tenant_a, tenant_b, client):
    client.post("/api/v1/customers", headers=tenant_a.h, json={"name": "سري جدا للشركة أ"})
    assert _search(client, tenant_b.h, "سري جدا") == {}
    client.post("/api/v1/roles", headers=tenant_a.h, json={"code": "lib_only", "name": "مكتبة بس", "permissions": ["library.read"]})
    _make_user(tenant_a, client, "libonly", "lib_only")
    assert "customers" not in _search(client, tenant_a.headers("libonly", "user-pass-123"), "سري جدا")


def test_search_needs_text(tenant_a, client):
    assert client.get("/api/v1/search", headers=tenant_a.h, params={"q": ""}).status_code == 422
    client.post("/api/v1/customers", headers=tenant_a.h, json={"name": "عميل عادي"})
    assert "customers" not in _search(client, tenant_a.h, "%")      # % and _ are searched as text, never as patterns
    assert "customers" not in _search(client, tenant_a.h, "_")
