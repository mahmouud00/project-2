"""A project in phases: each phase its own quotation (its sizes) and its own work order; the project adds them up
and every company sees its own only."""
from decimal import Decimal as D

from tests.test_business_flow import _setup, price_at_top
from tests.test_field_service import _accepted_order


def test_phases_of_one_project(platform, tenant_a, tenant_b, client):
    code = "PRJ"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo1 = _accepted_order(client, h, lib, branch, customer, code)          # phase 1: accepted, made into an order
    q1 = wo1["quotation_id"]
    r = client.post(f"/api/v1/quotations/{q1}/phase", headers=h, json={"project_name": "برج النيل"})
    assert r.status_code == 200, r.text
    phase2 = r.json()
    assert phase2["phase_name"] == "المرحلة 2"
    q2 = client.get(f"/api/v1/quotations/{phase2['id']}", headers=h).json()
    assert q2["customer_id"] == customer["id"] and q2["project_id"] == phase2["project_id"] and q2["lines"] == []
    first = client.get(f"/api/v1/quotations/{q1}", headers=h).json()
    assert first["project_id"] == phase2["project_id"] and first["phase_name"] == "المرحلة 1"
    assert client.get(f"/api/v1/work-orders/{wo1['id']}", headers=h).json()["project_id"] == phase2["project_id"]

    # phase 2 gets its own sizes and its own work order
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1200, "opening_height_mm": 1400, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6", "qty": 3}
    q2 = client.post(f"/api/v1/quotations/{q2['id']}/lines", headers=h, json=line).json()
    q2 = price_at_top(client, h, q2)
    q2 = client.post(f"/api/v1/quotations/{q2['id']}/status", headers=h, json={"version": q2["version"], "status": "accepted"}).json()
    wo2 = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q2["id"]}).json()
    assert wo2["id"] != wo1["id"] and wo2["project_id"] == phase2["project_id"]

    p = client.get(f"/api/v1/projects/{phase2['project_id']}", headers=h).json()
    assert p["name"] == "برج النيل" and p["number"].startswith("PJ")
    assert [x["phase_name"] for x in p["phases"]] == ["المرحلة 1", "المرحلة 2"]
    assert {x["work_order_id"] for x in p["phases"]} == {wo1["id"], wo2["id"]}
    assert D(p["ordered_total"]) == D(wo1["total"]) + D(wo2["total"]) and D(p["remaining"]) == D(p["ordered_total"])
    assert [x["id"] for x in client.get(f"/api/v1/projects?customer_id={customer['id']}", headers=h).json()] == [p["id"]]
    r = client.patch(f"/api/v1/projects/{p['id']}", headers=h, json={"version": p["version"], "name": "برج النيل - أ"})
    assert r.status_code == 200 and r.json()["name"] == "برج النيل - أ"
    # another company sees nothing
    assert client.get(f"/api/v1/projects/{p['id']}", headers=tenant_b.h).status_code == 404
    assert client.get("/api/v1/projects", headers=tenant_b.h).json() == []
