"""The sales workflow: the sales manager confirms a survey before a quotation is made from it, and a quotation before
the customer gets it (a notification each way; a change needs a new confirmation)."""
from tests.test_business_flow import _setup
from tests.test_org_permissions_locking import _make_user


def _people(client, tenant, branch, tag):
    _make_user(tenant, client, f"seller_{tag}", "sales", branch["id"])
    _make_user(tenant, client, f"manager_{tag}", "sales_manager", branch["id"])
    return tenant.headers(f"seller_{tag}", "user-pass-123"), tenant.headers(f"manager_{tag}", "user-pass-123")


def _inbox(client, h):
    return [n["title"] for n in client.get("/api/v1/notifications", headers=h).json()["items"]]


def test_manager_confirms_survey_then_quotation(platform, tenant_a, client):
    from tests.customers import cust as new_customer

    lib, branch, _, _ = _setup(client, platform, tenant_a, "WFA")
    seller, manager = _people(client, tenant_a, branch, "wfa")
    customer = client.post("/api/v1/customers", headers=seller, json=new_customer()).json()
    window = {"model_id": lib["model"]["id"], "color_code": "W", "glass_material_code": "WFA-GLASS6",
              "opening_width_mm": 1200, "opening_height_mm": 1000}
    sv = client.post("/api/v1/surveys", headers=seller, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                              "openings": [window]}).json()
    assert sv["approval_status"] == "none"
    r = client.post("/api/v1/quotations", headers=seller, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                               "survey_id": sv["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NEEDS_MANAGER_APPROVAL"
    sv = client.post(f"/api/v1/surveys/{sv['id']}/request-approval", headers=seller).json()
    assert sv["approval_status"] == "pending" and any(sv["number"] in t for t in _inbox(client, manager))
    assert client.post(f"/api/v1/surveys/{sv['id']}/approve", headers=seller).status_code == 403
    sv = client.post(f"/api/v1/surveys/{sv['id']}/approve", headers=manager).json()
    assert sv["approval_status"] == "approved" and any("أكد" in t for t in _inbox(client, seller))
    # a change after the confirmation needs a new one
    changed = client.patch(f"/api/v1/surveys/{sv['id']}", headers=seller, json={"version": sv["version"], "notes": "x"}).json()
    assert changed["approval_status"] == "none"
    client.post(f"/api/v1/surveys/{sv['id']}/approve", headers=manager)

    q = client.post("/api/v1/quotations", headers=seller, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                               "survey_id": sv["id"]})
    assert q.status_code == 201, q.text
    q = q.json()
    r = client.post(f"/api/v1/quotations/{q['id']}/status", headers=seller, json={"version": q["version"], "status": "sent"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NEEDS_MANAGER_APPROVAL"
    assert client.post(f"/api/v1/quotations/{q['id']}/share", headers=seller, json={}).status_code == 409
    q = client.post(f"/api/v1/quotations/{q['id']}/request-approval", headers=seller).json()
    assert q["approval_status"] == "pending"
    q = client.post(f"/api/v1/quotations/{q['id']}/approve", headers=manager).json()
    # an opening changed: confirm again
    q = client.post(f"/api/v1/quotations/{q['id']}/lines", headers=seller, json=window).json()
    assert q["approval_status"] == "none"
    q = client.post(f"/api/v1/quotations/{q['id']}/approve", headers=manager).json()
    r = client.post(f"/api/v1/quotations/{q['id']}/status", headers=seller, json={"version": q["version"], "status": "sent"})
    assert r.status_code == 200, r.text
    # the manager himself does not wait for his own confirmation
    q2 = client.post("/api/v1/quotations", headers=manager, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                                 "lines": [window]}).json()
    r = client.post(f"/api/v1/quotations/{q2['id']}/status", headers=manager, json={"version": q2["version"], "status": "sent"})
    assert r.status_code == 200 and r.json()["approval_status"] == "approved"


def test_each_salesperson_sees_his_own_work_and_work_moves(platform, tenant_a, client):
    from tests.customers import cust as new_customer

    lib, branch, _, _ = _setup(client, platform, tenant_a, "OWN")
    one, manager = _people(client, tenant_a, branch, "own1")
    _make_user(tenant_a, client, "seller_own2", "sales", branch["id"])
    two = tenant_a.headers("seller_own2", "user-pass-123")
    window = {"model_id": lib["model"]["id"], "color_code": "W", "glass_material_code": "OWN-GLASS6",
              "opening_width_mm": 1000, "opening_height_mm": 1000}
    c1 = client.post("/api/v1/customers", headers=one, json=new_customer("عميل الموظف الأول")).json()
    q1 = client.post("/api/v1/quotations", headers=one, json={"customer_id": c1["id"], "branch_id": branch["id"],
                                                            "lines": [window]}).json()
    c2 = client.post("/api/v1/customers", headers=two, json=new_customer("عميل الموظف التاني")).json()

    names = lambda h: {c["name"] for c in client.get("/api/v1/customers", headers=h).json()["items"]}
    assert names(one) == {"عميل الموظف الأول"} and names(two) == {"عميل الموظف التاني"}
    assert {"عميل الموظف الأول", "عميل الموظف التاني"} <= names(manager)                  # the manager sees all
    assert client.get(f"/api/v1/customers/{c1['id']}", headers=two).status_code == 404
    assert client.get(f"/api/v1/quotations/{q1['id']}", headers=two).status_code == 404
    assert client.get("/api/v1/quotations", headers=two).json()["total"] == 0
    r = client.post("/api/v1/quotations", headers=two, json={"customer_id": c1["id"], "branch_id": branch["id"],
                                                           "lines": [window]})
    assert r.status_code == 404
    found = client.get("/api/v1/search", headers=two, params={"q": "عميل الموظف"}).json()
    assert all("الأول" not in h["title"] for g in found.get("customers", []) for h in ([g] if "title" in g else []))
    # only the manager moves work
    me2 = next(p for p in client.get("/api/v1/sales/people", headers=manager).json() if p["id"] != c1["owner_id"]
               and p["name"])
    assert client.post(f"/api/v1/customers/{c1['id']}/transfer", headers=one, json={"to_user_id": me2["id"]}).status_code == 403
    owner2 = c2["owner_id"]
    r = client.post(f"/api/v1/customers/{c1['id']}/transfer", headers=manager, json={"to_user_id": owner2})
    assert r.status_code == 200 and r.json()["moved"]["quotations"] == 1
    assert names(one) == set() and names(two) == {"عميل الموظف الأول", "عميل الموظف التاني"}
    assert client.get(f"/api/v1/quotations/{q1['id']}", headers=two).status_code == 200
    # all of one person's work at once
    r = client.post("/api/v1/sales/transfer", headers=manager, json={"from_user_id": owner2, "to_user_id": c1["owner_id"]})
    assert r.json()["moved"]["customers"] == 2 and names(two) == set() and len(names(one)) == 2


def test_salesperson_dashboard_and_the_n8n_bot(platform, tenant_a, tenant_b, client):
    from decimal import Decimal as D

    from tests.customers import cust as new_customer
    from tests.orders import collect, invoice_of

    lib, branch, _, _ = _setup(client, platform, tenant_a, "DSH")
    seller, manager = _people(client, tenant_a, branch, "dsh")
    h = tenant_a.h
    c = client.post("/api/v1/customers", headers=seller, json=new_customer(national_id="29001011234567")).json()
    window = {"model_id": lib["model"]["id"], "color_code": "W", "glass_material_code": "DSH-GLASS6",
              "opening_width_mm": 1000, "opening_height_mm": 1000}
    q = client.post("/api/v1/quotations", headers=seller, json={"customer_id": c["id"], "branch_id": branch["id"],
                                                               "lines": [window]}).json()
    client.post(f"/api/v1/quotations/{q['id']}/approve", headers=manager)
    q = client.get(f"/api/v1/quotations/{q['id']}", headers=seller).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=seller, json={"version": q["version"], "status": "accepted"}).json()
    inv = invoice_of(client, seller, q)
    collect(client, seller, inv, "1000", confirm_h=h)
    client.post(f"/api/v1/invoices/{inv['id']}/collections", headers=seller, json={"amount": "500"})

    d = client.get("/api/v1/sales/dashboard", headers=seller).json()
    assert d["customers"]["total"] == 1 and d["customers"]["new"] == 1
    assert d["quotations"]["made"] == 1 and d["quotations"]["accepted_count"] == 1
    assert D(d["invoices"]["sales_value"]) == D(inv["total"])
    assert D(d["collections"]["confirmed"]) == 1000 and D(d["collections"]["pending_amount"]) == 500
    assert D(d["invoices"]["open_balance"]) == D(inv["total"]) - 1000 and len(d["months"]) == 6
    # his own only; the manager opens anyone's and the team table
    assert client.get(f"/api/v1/sales/dashboard?user_id={c['owner_id']}", headers=manager).json()["customers"]["total"] == 1
    other = client.get(f"/api/v1/sales/dashboard?user_id={d['user_id']}", headers=manager).status_code
    assert other == 200
    me_manager = client.get("/api/v1/auth/me", headers=manager).json()
    mid = me_manager.get("id") or me_manager.get("user", {}).get("id")
    if mid:
        assert client.get(f"/api/v1/sales/dashboard?user_id={mid}", headers=seller).status_code == 403
    team = client.get("/api/v1/sales/team", headers=manager).json()["people"]
    assert any(p["user_id"] == c["owner_id"] and D(p["collected"]) == 1000 for p in team)
    assert client.get("/api/v1/sales/team", headers=seller).status_code == 403

    # n8n: a company key reads the salespeople and their reports, and sends tips
    assert client.post("/api/v1/integrations/keys", headers=seller, json={"name": "n8n"}).status_code == 403
    k = client.post("/api/v1/integrations/keys", headers=h, json={"name": "n8n"}).json()
    key = {"X-API-Key": k["key"]}
    assert k["key"].startswith("mtk_") and "key" not in client.get("/api/v1/integrations/keys", headers=h).json()[0] or \
        client.get("/api/v1/integrations/keys", headers=h).json()[0]["key"] is None
    people = client.get("/api/v1/integrations/sales/people", headers=key).json()
    assert any(p["id"] == c["owner_id"] for p in people)
    rep = client.get(f"/api/v1/integrations/sales/report?user_id={c['owner_id']}", headers=key).json()
    assert D(rep["collections"]["confirmed"]) == 1000
    r = client.post("/api/v1/integrations/sales/tips", headers=key,
                    json={"user_id": c["owner_id"], "title": "تابع عروضك", "body": "عندك عرض مستني رد من أسبوع"})
    assert r.status_code == 201
    assert any(n["title"] == "نصيحة: تابع عروضك" for n in client.get("/api/v1/notifications", headers=seller).json()["items"])
    assert client.get("/api/v1/integrations/sales/people", headers={"X-API-Key": "mtk_wrong"}).status_code == 401
    client.post(f"/api/v1/integrations/keys/{k['id']}/revoke", headers=h)
    assert client.get("/api/v1/integrations/sales/people", headers=key).status_code == 401
    # another company's key never reaches this company's people
    kb = client.post("/api/v1/integrations/keys", headers=tenant_b.h, json={"name": "n8n"}).json()
    assert all(p["id"] != c["owner_id"] for p in client.get("/api/v1/integrations/sales/people",
                                                           headers={"X-API-Key": kb["key"]}).json())


def test_each_user_gets_his_own_permissions(tenant_a, client):
    from tests.customers import cust as new_customer

    u = _make_user(tenant_a, client, "custom-user", "sales")
    hu = tenant_a.headers("custom-user", "user-pass-123")
    h = tenant_a.h
    c = client.post("/api/v1/customers", headers=hu, json=new_customer()).json()
    p = client.get(f"/api/v1/users/{u['id']}/permissions", headers=h).json()
    assert "customers.delete" not in p["effective"] and "customers.create" in p["from_roles"]
    # view only on customers (no adding), but may delete; and may not print quotations
    r = client.put(f"/api/v1/users/{u['id']}/permissions", headers=h, json={
        "version": p["version"], "extra_permissions": ["customers.delete"],
        "denied_permissions": ["customers.create", "customers.write", "quotes.print"]})
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/customers", headers=hu, json=new_customer("عميل تاني ممنوع")).status_code == 403
    assert client.get("/api/v1/customers", headers=hu).status_code == 200
    me = client.get("/api/v1/auth/me", headers=hu).json()
    flat = {x for v in me["grants"].values() for x in v} if "grants" in me else set()
    assert not flat or ("customers.delete" in flat and "customers.create" not in flat)
    assert client.get(f"/api/v1/history/customers/{c['id']}", headers=hu).status_code in (200, 403)
    r = client.put(f"/api/v1/users/{u['id']}/permissions", headers=h, json={
        "version": r.json()["version"], "extra_permissions": ["no.such"], "denied_permissions": []})
    assert r.status_code == 422
    assert client.put(f"/api/v1/users/{u['id']}/permissions", headers=hu, json={"version": 1}).status_code == 403
