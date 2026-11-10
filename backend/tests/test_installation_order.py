"""أمر التركيب: every window on its own row with where it goes; the job's technician and those allowed see it."""
from datetime import datetime, timedelta, timezone

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from tests.test_org_permissions_locking import _make_user


def test_installation_order(platform, tenant_a, client):
    code = "INST"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _accepted_order(client, h, lib, branch, customer, code)          # one line of 2 windows
    page = client.get(f"/api/v1/work-orders/{wo['id']}/print/installation", headers=h)
    assert page.status_code == 200, page.text
    assert "أمر تركيب" in page.text and "1 من 2" in page.text and "2 من 2" in page.text

    tech = _make_user(tenant_a, client, "inst-tech", "technician")
    other = _make_user(tenant_a, client, "inst-tech2", "technician")
    sales = _make_user(tenant_a, client, "inst-sales", "sales")
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    job = client.post("/api/v1/field/jobs", headers=h, json={
        "kind": "installation", "customer_id": customer["id"], "branch_id": branch["id"], "work_order_id": wo["id"],
        "technician_id": tech["id"], "scheduled_at": when}).json()
    url = f"/api/v1/field/jobs/{job['id']}/installation-order"
    r = client.get(url, headers=tenant_a.headers("inst-tech", "user-pass-123"))
    assert r.status_code == 200 and customer["name"] in r.text
    assert client.get(url, headers=tenant_a.headers("inst-tech2", "user-pass-123")).status_code == 403   # not their job
    hs = tenant_a.headers("inst-sales", "user-pass-123")
    assert client.get(f"/api/v1/work-orders/{wo['id']}/print/installation", headers=hs).status_code == 403   # no permission
    assert other and sales


def test_survey_with_two_windows_becomes_two_lines(platform, tenant_a, client):
    code = "INSV"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    s = client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                    "openings": [{"location": "الصالة", "model_id": lib["model"]["id"], "opening_width_mm": 1000,
                                  "opening_height_mm": 1000, "qty": 2, "color_code": "W"}]})
    assert s.status_code == 201, s.text
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "survey_id": s.json()["id"], "lines": []})
    assert q.status_code == 201, q.text
    lines = [l for l in q.json()["lines"] if not l.get("parent_line_id")]
    assert [int(l["qty"]) for l in lines] == [1, 1] and {l["location"] for l in lines} == {"الصالة"}
