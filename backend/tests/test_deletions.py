"""الحذف بعد ٣٠ يوم: a delete waits with a countdown; the permanent delete permission erases it at once; the one who
asked (or that permission) takes it back; open work using a deleted library model is told to replace it."""
from datetime import datetime, timedelta

from app.db.base import utcnow
from tests.delete_helpers import delete_now
from tests.test_business_flow import _setup, price_at_top
from tests.test_org_permissions_locking import _make_user


def _inbox(client, h):
    return [n["title"] for n in client.get("/api/v1/notifications", headers=h).json()["items"]]


def test_delete_waits_30_days_unless_erased_now(tenant_a, client):
    admin = tenant_a.h
    client.post("/api/v1/roles", headers=admin, json={"code": "custdel", "name": "عملاء",
                                                       "permissions": ["customers.read", "customers.create",
                                                                       "customers.delete"]})
    _make_user(tenant_a, client, "deleter1", "custdel")
    h = tenant_a.headers("deleter1", "user-pass-123")
    cust = client.post("/api/v1/customers", headers=h, json={"name": "عميل للحذف"}).json()

    r = client.delete(f"/api/v1/customers/{cust['id']}", headers=h)
    assert r.status_code == 200 and r.json()["result"] == "scheduled"
    rid = r.json()["request_id"]
    assert client.delete(f"/api/v1/customers/{cust['id']}", headers=h).json()["request_id"] == rid   # same request
    assert client.get(f"/api/v1/customers/{cust['id']}", headers=h).status_code == 200      # still there meanwhile
    mine = next(x for x in client.get("/api/v1/deletions", headers=h).json() if x["id"] == rid)
    assert mine["label"] == f"العميل {cust['code']}" and mine["can_cancel"] and not mine["can_delete_now"]
    wait = datetime.fromisoformat(mine["due_at"]) - datetime.fromisoformat(mine["requested_at"])
    assert wait == timedelta(days=30) and mine["kind"] == "customers" and mine["target_id"] == cust["id"]
    assert any(t.startswith("طلب حذف العميل") for t in _inbox(client, admin))            # the administrator hears

    # without the permanent delete permission it cannot be erased now; the one who asked can take it back
    assert client.post(f"/api/v1/deletions/{rid}/now", headers=h).status_code == 403
    r = client.post(f"/api/v1/deletions/{rid}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/deletions/{rid}/cancel", headers=h).json()["error"]["code"] == "DELETION_NOT_PENDING"

    # asked again: the administrator erases it from the countdown
    rid = client.delete(f"/api/v1/customers/{cust['id']}", headers=h).json()["request_id"]
    r = client.post(f"/api/v1/deletions/{rid}/now", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get(f"/api/v1/customers/{cust['id']}", headers=h).status_code == 404

    # someone else cannot take back another's deletion; after 30 days it goes by itself
    other = client.post("/api/v1/customers", headers=h, json={"name": "عميل تاني"}).json()
    rid = client.delete(f"/api/v1/customers/{other['id']}", headers=h).json()["request_id"]
    _make_user(tenant_a, client, "deleter2", "custdel")
    h2 = tenant_a.headers("deleter2", "user-pass-123")
    assert client.post(f"/api/v1/deletions/{rid}/cancel", headers=h2).status_code == 403
    from app.modules.deletions.router import run_due_deletions
    run_due_deletions(now=utcnow() + timedelta(days=29))
    assert client.get(f"/api/v1/customers/{other['id']}", headers=h).status_code == 200
    run_due_deletions(now=utcnow() + timedelta(days=30, minutes=1))
    assert client.get(f"/api/v1/customers/{other['id']}", headers=h).status_code == 404
    done = client.get("/api/v1/deletions?status=done", headers=h).json()
    assert any(x["id"] == rid for x in done)


def test_same_rules_as_before_and_failures(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "DLR")
    h = tenant_a.h
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": "DLR-GLASS6"}
    # an issued invoice still cannot be deleted: refused when asked, nothing waits
    inv = client.post("/api/v1/invoices", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                          "lines": [{"kind": "service", "description": "x", "qty": "1",
                                                                     "unit_price": "10"}]}).json()
    inv = client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=h, json={"version": inv["version"]}).json()
    r = client.delete(f"/api/v1/invoices/{inv['id']}", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVOICE_ISSUED"
    assert all(x["target_id"] != inv["id"] for x in client.get("/api/v1/deletions", headers=h).json())
    # a work order that gets money while it waits is not deleted: the request fails with the reason
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    q = price_at_top(client, h, q)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"],
                                                                              "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    rid = client.delete(f"/api/v1/work-orders/{wo['id']}", headers=h).json()["request_id"]
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "DLR", "name": "خزنة", "branch_id": branch["id"]}).json()
    client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "50", "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"]})
    r = client.post(f"/api/v1/deletions/{rid}/now", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "WO_IN_USE"
    failed = client.get("/api/v1/deletions?status=failed", headers=h).json()
    assert any(x["id"] == rid and x["note"] == "WO_IN_USE" for x in failed)
    assert any(t.endswith("ماتحذفش") and wo["number"] in t for t in _inbox(client, h))    # the one who asked hears
    assert client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).status_code == 200


def test_deleted_model_open_work_is_told_closed_work_keeps_it(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "DLM")
    h = tenant_a.h
    line = {"location": "صالة", "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000,
            "color_code": "W", "glass_material_code": "DLM-GLASS6"}
    _make_user(tenant_a, client, "seller_dlm", "sales")
    hs = tenant_a.headers("seller_dlm", "user-pass-123")
    open_q = client.post("/api/v1/quotations", headers=hs, json={"customer_id": customer["id"],
                                                               "branch_id": branch["id"], "lines": [line]}).json()
    closed = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"],
                                                              "branch_id": branch["id"], "lines": [line]}).json()
    closed = price_at_top(client, h, closed)
    closed = client.post(f"/api/v1/quotations/{closed['id']}/status", headers=h,
                         json={"version": closed["version"], "status": "accepted"}).json()

    model = lib["model"]
    r = client.delete(f"/api/v1/library/models/{model['id']}", headers=platform.h)
    assert r.json()["result"] == "scheduled"
    soon = _inbox(client, hs)
    assert any(f"«النموذج {model['code']}» هيتحذف" in t and open_q["number"] in t for t in soon)
    assert not any(closed["number"] in t for t in soon)
    assert any(open_q["number"] in t for t in _inbox(client, h))      # the sales managers (admin) too

    assert delete_now(client, platform.h, f"/api/v1/library/models/{model['id']}").json()["result"] == "deleted"
    assert any(f"«النموذج {model['code']}» اتحذف" in t for t in _inbox(client, hs))
    # gone from the library; the old quotation still shows what it was made with
    models = client.get(f"/api/v1/library/models?system_id={lib['system']['id']}", headers=h).json()
    assert all(m["id"] != model["id"] for m in models)
    assert client.get(f"/api/v1/quotations/{open_q['id']}", headers=h).json()["lines"][0]["model_deleted"]
    old = client.get(f"/api/v1/quotations/{closed['id']}", headers=h).json()
    assert old["lines"][0]["model_code"] == model["code"] and old["total"] == closed["total"]
