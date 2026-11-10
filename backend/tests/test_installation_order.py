"""التركيب: after manufacturing the order reaches «تركيب»; the installations manager gives it to a technician; the
installation order (every window on its own row with where it goes) appears then; the job done delivers the order."""
from datetime import datetime, timedelta, timezone

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from tests.test_org_permissions_locking import _make_user


def _to(client, h, wo, stage):
    r = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": stage})
    assert r.status_code == 200, r.text
    return r.json()


def _made(client, h, wo, branch, customer, code):
    """approve the sale, pay the deposit and make it: the order is then at «جودة»."""
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/approve-sale", headers=h, json={"version": wo["version"]}).json()
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": f"B{code}", "name": "خزينة", "branch_id": branch["id"]}).json()
    client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": wo["deposit_required"], "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"]})
    wo = client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()
    for stage in ("approved", "manufacturing", "assembly", "quality"):
        wo = _to(client, h, wo, stage)
    return wo


def test_installation_stage_and_order(platform, tenant_a, client):
    code = "INST"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _accepted_order(client, h, lib, branch, customer, code)          # one line of 2 windows (saved before)
    tech = _make_user(tenant_a, client, "inst-tech", "technician")
    _make_user(tenant_a, client, "inst-tech2", "technician")
    _make_user(tenant_a, client, "inst-sales", "sales")
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    job_in = {"kind": "installation", "customer_id": customer["id"], "branch_id": branch["id"], "work_order_id": wo["id"],
              "technician_id": tech["id"], "scheduled_at": when}
    # not before the order is made
    r = client.post("/api/v1/field/jobs", headers=h, json=job_in)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_READY_FOR_INSTALLATION"
    r = client.get(f"/api/v1/work-orders/{wo['id']}/print/installation", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_READY_FOR_INSTALLATION"

    wo = _to(client, h, _made(client, h, wo, branch, customer, code), "installation")
    waiting = [i for i in client.get("/api/v1/field/installations", headers=h).json() if i["work_order_id"] == wo["id"]]
    assert waiting and waiting[0]["windows"] == 2 and waiting[0]["job_id"] is None
    page = client.get(f"/api/v1/work-orders/{wo['id']}/print/installation", headers=h)
    assert page.status_code == 200 and "1 من 2" in page.text and "2 من 2" in page.text

    job = client.post("/api/v1/field/jobs", headers=h, json=job_in)
    assert job.status_code == 201, job.text
    job = job.json()
    url = f"/api/v1/field/jobs/{job['id']}/installation-order"
    ht = tenant_a.headers("inst-tech", "user-pass-123")
    assert client.get(url, headers=ht).status_code == 200
    assert client.get(url, headers=tenant_a.headers("inst-tech2", "user-pass-123")).status_code == 403   # not their job
    hs = tenant_a.headers("inst-sales", "user-pass-123")
    assert client.get(f"/api/v1/work-orders/{wo['id']}/print/installation", headers=hs).status_code == 403
    assert [i for i in client.get("/api/v1/field/installations", headers=h).json()
            if i["work_order_id"] == wo["id"]][0]["technician_name"]

    # the technician finishes: the order is delivered
    for status in ("on_way", "arrived", "done"):
        assert client.post(f"/api/v1/field/jobs/{job['id']}/status", headers=ht, json={"status": status}).status_code == 200
    assert client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()["stage"] == "delivered"


def test_an_order_without_installation_goes_to_delivery(platform, tenant_a, client):
    code = "INSD"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _made(client, h, _accepted_order(client, h, lib, branch, customer, code), branch, customer, code)
    assert _to(client, h, wo, "delivered")["stage"] == "delivered"


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
