"""«ابدأ هنا»: a new factory's first steps, read from its own data."""
from tests.test_business_flow import _setup
from tests.test_sharing import _quote


def _steps(client, h):
    r = client.get("/api/v1/company/setup", headers=h)
    assert r.status_code == 200, r.text
    return r.json(), {s["id"]: s["done"] for s in r.json()["steps"]}


def test_first_steps_follow_the_data(platform, tenant_a, client):
    h = tenant_a.h
    out, done = _steps(client, h)
    assert out["total"] == 5 and not out["dismissed"]
    assert not done["company"] and not done["users"] and not done["quotation"] and not done["prices"]

    lib, branch, _, customer = _setup(client, platform, tenant_a, "STP")
    _quote(client, h, lib, branch, customer, "STP")
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        **company["settings"], "phone": "0221234567"}})
    _, done = _steps(client, h)
    assert done["systems"] and done["quotation"] and not done["company"]       # the logo is still missing

    roles = client.get("/api/v1/roles", headers=h).json()
    role = roles[0] if isinstance(roles, list) else roles["items"][0]
    r = client.post("/api/v1/users", headers=h, json={"username": "sales1", "full_name": "بياع", "password": "Sales-pass-123",
                                                      "roles": [{"role_id": role["id"], "branch_id": None}]})
    assert r.status_code == 201, r.text
    assert _steps(client, h)[1]["users"]

    # closing it keeps it closed, also after the company data is saved again
    assert client.post("/api/v1/company/setup/dismiss", headers=h, json={}).json()["dismissed"]
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        **company["settings"], "setup_dismissed": False}})
    assert _steps(client, h)[0]["dismissed"]


def test_only_for_who_manages_the_company(tenant_a, client):
    assert client.get("/api/v1/company/setup").status_code == 401
