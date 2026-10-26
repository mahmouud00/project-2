"""Survey location, stage durations / progress, goods order from a work order, maintenance requests,
technician jobs and GPS tracking (only during a job)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

from tests.test_business_flow import _setup
from tests.test_org_permissions_locking import _make_user


def _accepted_order(client, h, lib, branch, customer, code):
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6", "qty": 2}
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    return client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()


def test_survey_location_from_map_link(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "LOC")
    h = tenant_a.h
    link = "https://www.google.com/maps/place/x/@30.0444,31.2357,17z/data=!3m1!4b1!3d30.0445!4d31.2358"
    sv = client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                        "location_url": link}).json()
    assert D(sv["latitude"]) == D("30.0445") and D(sv["longitude"]) == D("31.2358") and sv["location_url"] == link
    sv = client.patch(f"/api/v1/surveys/{sv['id']}", headers=h, json={"version": sv["version"],
                                                                    "location_url": "30.1, 31.2"}).json()
    assert D(sv["latitude"]) == D("30.1")
    html = client.get(f"/api/v1/surveys/{sv['id']}/print", headers=h).text
    assert "maps?q=30.100000,31.200000" not in html and "<svg" in html and "30.100000" in html  # QR + coordinates
    sv = client.patch(f"/api/v1/surveys/{sv['id']}", headers=h, json={"version": sv["version"], "location_url": ""}).json()
    assert sv["location_url"] is None and sv["latitude"] is None


def test_stage_progress():
    from app.modules.production.progress import progress

    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    durations = {"survey": D(1), "quotation": D(1), "approved": D(1), "manufacturing": D(4), "assembly": D(2),
                 "quality": D(1)}
    wo = SimpleNamespace(stage="manufacturing", created_at=now - timedelta(days=10))
    p = progress(wo, {"manufacturing": now - timedelta(days=2)}, durations, now)
    assert p["progress_pct"] == 50 and not p["late"]                   # 3 + 2 of 10 days
    assert p["expected_delivery"] == (now + timedelta(days=2 + 3)).date()
    p = progress(wo, {"manufacturing": now - timedelta(days=6)}, durations, now)
    assert p["progress_pct"] == 70 and p["late"]                        # capped at the stage's 4 days, late
    assert progress(SimpleNamespace(stage="delivered", created_at=now), {}, durations, now)["progress_pct"] == 100
    assert progress(SimpleNamespace(stage="cancelled", created_at=now), {}, durations, now)["progress_pct"] is None


def test_work_order_shows_progress(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "PRG")
    wo = _accepted_order(client, tenant_a.h, lib, branch, customer, "PRG")
    assert wo["progress_pct"] is not None and wo["expected_delivery"] and wo["late"] is False
    listed = client.get(f"/api/v1/work-orders?customer_id={customer['id']}", headers=tenant_a.h).json()["items"][0]
    assert listed["progress_pct"] == wo["progress_pct"]


def test_goods_order_from_work_order(platform, tenant_a, client):
    code = "GOO"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _accepted_order(client, h, lib, branch, customer, code)
    needs = client.get(f"/api/v1/work-orders/{wo['id']}/material-needs", headers=h)
    assert needs.status_code == 200, needs.text
    by = {n["sku"]: n for n in needs.json()}
    frame = by[f"{code}-FRAME-W"]
    assert frame["kind"] == "profile" and frame["bars"] >= 1
    assert D(frame["qty"]) == D(frame["bar_length_mm"]) * frame["bars"] / 1000          # whole bars, in metres
    assert by[f"{code}-GLASS6"]["kind"] == "glass" and by[f"{code}-GLASS6"]["pieces"] == 4
    assert D(by[f"{code}-HANDLE-W"]["qty"]) == 4 and D(by[f"{code}-WHEEL-W"]["qty"]) == 8   # accessories per model x qty
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد قطاعات"}).json()
    wh = client.post("/api/v1/warehouses", headers=h, json={"code": "GW", "name": "مخزن", "branch_id": branch["id"]}).json()
    po = client.post("/api/v1/purchase-orders", headers=h, json={
        "supplier_id": sup["id"], "branch_id": branch["id"], "warehouse_id": wh["id"], "work_order_id": wo["id"],
        "lines": [{"sku": n["sku"], "qty": n["qty"], "unit_cost": n["unit_cost"] or "0"} for n in needs.json()]})
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["customer_id"] == customer["id"] and po["work_order_id"] == wo["id"] and po["status"] == "draft"
    assert client.get(f"/api/v1/purchase-orders?customer_id={customer['id']}", headers=h).json()["total"] == 1


def test_maintenance_and_technician_tracking(platform, tenant_a, tenant_b, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "MNT")
    h = tenant_a.h
    m = client.post("/api/v1/maintenance", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "description": "الضلفة مش بتقفل",
        "location_url": "https://maps.google.com/?q=30.05,31.24"})
    assert m.status_code == 201, m.text
    m = m.json()
    assert m["number"].startswith("MT-") and m["status"] == "open" and m["address"] == "القاهرة" and D(m["latitude"]) == D("30.05")
    assert client.get(f"/api/v1/maintenance?customer_id={customer['id']}", headers=h).json()["total"] == 1

    tech = _make_user(tenant_a, client, "tech1", "technician")
    ht = tenant_a.headers("tech1", "user-pass-123")
    # the technician cannot assign jobs nor see the map; an admin (not a technician) cannot be assigned
    me = client.get("/api/v1/auth/me", headers=h).json()
    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    job = {"kind": "maintenance", "customer_id": customer["id"], "branch_id": branch["id"], "maintenance_id": m["id"],
           "scheduled_at": when}
    r = client.post("/api/v1/field/jobs", headers=h, json={**job, "technician_id": me["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_TECHNICIAN"
    assert client.post("/api/v1/field/jobs", headers=ht, json={**job, "technician_id": tech["id"]}).status_code == 403
    assert client.get("/api/v1/field/technicians", headers=ht).status_code == 403
    j = client.post("/api/v1/field/jobs", headers=h, json={**job, "technician_id": tech["id"]})
    assert j.status_code == 201, j.text
    j = j.json()
    assert D(j["latitude"]) == D("30.05") and j["customer_name"] == customer["name"] and j["reference"] == m["number"]
    assert client.get(f"/api/v1/maintenance/{m['id']}", headers=h).json()["status"] == "scheduled"

    # no job in progress: the phone's location is refused (no tracking off duty)
    point = {"latitude": "30.01", "longitude": "31.2", "accuracy_m": "12"}
    r = client.post("/api/v1/field/locations", headers=ht, json=point)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_ACTIVE_JOB"
    mine = client.get("/api/v1/field/jobs?mine=true", headers=ht).json()
    assert [x["id"] for x in mine] == [j["id"]]
    assert client.post(f"/api/v1/field/jobs/{j['id']}/status", headers=ht, json={"status": "cancelled"}).status_code == 403
    assert client.post(f"/api/v1/field/jobs/{j['id']}/status", headers=ht, json={"status": "on_way"}).json()["status"] == "on_way"
    assert client.post("/api/v1/field/locations", headers=ht, json=point).status_code == 201
    techs = client.get("/api/v1/field/technicians", headers=h).json()
    t = next(x for x in techs if x["user_id"] == tech["id"])
    assert D(t["last"]["latitude"]) == D("30.01") and t["active_job"]["id"] == j["id"]
    assert all(x["user_id"] != me["id"] for x in techs)
    log = client.get(f"/api/v1/privacy/access-log?subject_id={tech['id']}", headers=h).json()["items"]
    assert any(e["subject_type"] == "user" and "latitude" in e["fields"] for e in log)   # reading locations is logged
    assert client.post(f"/api/v1/field/jobs/{j['id']}/status", headers=ht, json={"status": "arrived"}).status_code == 200
    done = client.post(f"/api/v1/field/jobs/{j['id']}/status", headers=ht, json={"status": "done", "note": "اتغيرت العجل"}).json()
    assert done["status"] == "done" and done["result_note"] == "اتغيرت العجل" and done["finished_at"]
    assert client.get(f"/api/v1/maintenance/{m['id']}", headers=h).json()["status"] == "done"
    assert len(client.get(f"/api/v1/field/jobs/{j['id']}/track", headers=h).json()) == 1
    assert client.post("/api/v1/field/locations", headers=ht, json=point).status_code == 409   # job finished
    # another company sees none of it
    assert client.get(f"/api/v1/maintenance/{m['id']}", headers=tenant_b.h).status_code == 404
    assert client.get("/api/v1/field/jobs", headers=tenant_b.h).json() == []


def test_old_locations_are_erased(platform, tenant_a, client):
    from app.db.session import system_session
    from app.modules.field.models import TechnicianLocation
    from app.modules.field.router import purge_old_locations
    import uuid

    db = system_session()
    try:
        uid = db.execute(__import__("sqlalchemy").text("SELECT id FROM users WHERE company_id = :c LIMIT 1"),
                         {"c": tenant_a.id}).scalar()
        old = TechnicianLocation(id=uuid.uuid4(), company_id=tenant_a.id, user_id=uid, latitude=D(30), longitude=D(31),
                                 at=datetime.now(timezone.utc) - timedelta(days=40))
        db.add(old)
        db.commit()
        assert purge_old_locations(db, 30) >= 1
        db.commit()
        assert db.get(TechnicianLocation, old.id) is None
    finally:
        db.close()


def test_tech_page_is_served(client):
    r = client.get("/tech")
    assert r.status_code == 200 and "field/jobs?mine=true" in r.text and "geolocation" in r.text
    assert client.get("/tech/manifest.webmanifest").json()["start_url"] == "/tech"
    assert client.get("/tech/icon.png").status_code == 200
