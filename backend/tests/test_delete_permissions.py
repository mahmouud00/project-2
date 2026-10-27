"""Separate add / delete permissions, and what "delete" means for each kind of record."""
from decimal import Decimal as D

from tests.test_business_flow import _setup
from tests.test_org_permissions_locking import _make_user


def test_add_and_delete_need_their_own_permission(tenant_a, client):
    r = client.post("/api/v1/roles", headers=tenant_a.h, json={"code": "editor", "name": "تعديل بس",
                                                               "permissions": ["customers.read", "customers.write"]})
    assert r.status_code == 201, r.text
    _make_user(tenant_a, client, "editor1", "editor")
    h = tenant_a.headers("editor1", "user-pass-123")
    r = client.post("/api/v1/customers", headers=h, json={"name": "عميل"})
    assert r.status_code == 403 and r.json()["error"]["details"]["permission"] == "customers.create"
    cust = client.post("/api/v1/customers", headers=tenant_a.h, json={"name": "عميل"}).json()
    assert client.patch(f"/api/v1/customers/{cust['id']}", headers=h,
                        json={"version": cust["version"], "phone": "0100"}).status_code == 200
    r = client.delete(f"/api/v1/customers/{cust['id']}", headers=h)
    assert r.status_code == 403 and r.json()["error"]["details"]["permission"] == "customers.delete"
    # the built-in sales role can add but not delete
    _make_user(tenant_a, client, "sales9", "sales")
    hs = tenant_a.headers("sales9", "user-pass-123")
    assert client.post("/api/v1/customers", headers=hs, json={"name": "عميل 2"}).status_code == 201
    assert client.delete(f"/api/v1/customers/{cust['id']}", headers=hs).status_code == 403
    # the administrator can delete; the customer disappears from lists
    assert client.delete(f"/api/v1/customers/{cust['id']}", headers=tenant_a.h).json() == {"result": "deleted"}
    assert client.get(f"/api/v1/customers/{cust['id']}", headers=tenant_a.h).status_code == 404


def test_what_delete_does(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "DEL")
    h = tenant_a.h
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": "DEL-GLASS6"}
    # survey and an unused quotation: deleted
    sv = client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"]}).json()
    assert client.delete(f"/api/v1/surveys/{sv['id']}", headers=h).json()["result"] == "deleted"
    assert client.get(f"/api/v1/surveys/{sv['id']}", headers=h).status_code == 404
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    assert client.delete(f"/api/v1/quotations/{q['id']}", headers=h).json()["result"] == "deleted"
    # a quotation with a work order stays; the work order with a payment stays (cancel it instead)
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    r = client.delete(f"/api/v1/quotations/{q['id']}", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUOTE_IN_USE"
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "DB1", "name": "خزنة", "branch_id": branch["id"]}).json()
    tx = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "100", "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"]}).json()
    r = client.delete(f"/api/v1/work-orders/{wo['id']}", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "WO_IN_USE"
    # money is never deleted: a cashbox with history is deactivated; a transaction is reversed
    assert client.delete(f"/api/v1/cashboxes/{box['id']}", headers=h).json()["result"] == "deactivated"
    rev = client.post(f"/api/v1/cash-transactions/{tx['id']}/reverse", headers=h, json={"note": "غلط"})
    assert rev.status_code == 201 and rev.json()["direction"] == "out" and D(rev.json()["amount"]) == 100
    empty = client.post("/api/v1/cashboxes", headers=h, json={"code": "DB2", "name": "x", "branch_id": branch["id"]}).json()
    assert client.delete(f"/api/v1/cashboxes/{empty['id']}", headers=h).json()["result"] == "deleted"
    # a price list used by quotations is deactivated, an unused one deleted
    assert client.delete(f"/api/v1/price-lists/{pl['id']}", headers=h).json()["result"] == "deactivated"
    pl2 = client.post("/api/v1/price-lists", headers=h, json={"code": "TMP", "name": "مؤقتة"}).json()
    assert client.delete(f"/api/v1/price-lists/{pl2['id']}", headers=h).json()["result"] == "deleted"
    # invoices: a draft is deleted, an issued one must be cancelled
    inv = client.post("/api/v1/invoices", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                          "lines": [{"kind": "service", "description": "تركيب", "qty": "1",
                                                                     "unit_price": "50"}]})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert client.delete(f"/api/v1/invoices/{inv['id']}", headers=h).json()["result"] == "deleted"
    # suppliers soft-deleted; draft purchase orders deleted
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد"}).json()
    po = client.post("/api/v1/purchase-orders", headers=h, json={"supplier_id": sup["id"], "branch_id": branch["id"],
                                                               "lines": [{"sku": "DEL-FRAME-W", "qty": "1", "unit_cost": "5"}]}).json()
    assert client.delete(f"/api/v1/purchase-orders/{po['id']}", headers=h).json()["result"] == "deleted"
    assert client.delete(f"/api/v1/suppliers/{sup['id']}", headers=h).json()["result"] == "deleted"


def test_library_delete(platform, tenant_a, client):
    from tests.library_helpers import build_library
    h = platform.h
    # never published: the whole system goes, with its constants, materials, models and tests
    draft = build_library(client, platform, code="DLD", publish=False)
    sid = draft["system"]["id"]
    assert client.delete(f"/api/v1/library/systems/{sid}", headers=h).json() == {"result": "deleted"}
    assert client.get(f"/api/v1/library/systems/{sid}", headers=h).status_code == 404
    assert client.get("/api/v1/library/materials?q=DLD-", headers=h).json()["items"] == []
    # published: the system, its model and its materials stay frozen and are only deactivated
    lib = build_library(client, platform, code="DLP")
    r = client.delete("/api/v1/library/materials/" + client.get(
        "/api/v1/library/materials?q=DLP-FRAME", headers=h).json()["items"][0]["id"], headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "MATERIAL_IN_USE" and r.json()["error"]["details"] == ["SL2"]
    assert client.delete(f"/api/v1/library/models/{lib['model']['id']}", headers=h).json()["result"] == "deactivated"
    mat = client.get("/api/v1/library/materials?q=DLP-FRAME", headers=h).json()["items"][0]
    assert client.delete(f"/api/v1/library/materials/{mat['id']}", headers=h).json()["result"] == "deactivated"
    assert client.delete(f"/api/v1/library/systems/{lib['system']['id']}", headers=h).json()["result"] == "deactivated"
    assert client.get(f"/api/v1/library/systems/{lib['system']['id']}", headers=h).json()["is_active"] is False
    # a new, unpublished model is deleted
    m = client.post("/api/v1/library/models", headers=h, json={
        "system_id": lib["system"]["id"], "code": "NEW", "name": "جديد", "category": "window",
        "definition": {"params": [], "formulas": [], "pieces": [], "glass": [], "accessories": [], "checks": []}})
    assert m.status_code == 201, m.text
    assert client.delete(f"/api/v1/library/models/{m.json()['id']}", headers=h).json()["result"] == "deleted"
    # a company cannot delete MYTech's library, and needs library.delete for its own rows
    r = client.delete(f"/api/v1/library/models/{lib['model']['id']}", headers=tenant_a.h)
    assert r.status_code == 403
    own = client.post("/api/v1/library/systems", headers=tenant_a.h, json={
        "code": "OWN", "name": "خاص", "material_type": "upvc", "unit": "cm"}).json()
    r = client.post("/api/v1/roles", headers=tenant_a.h, json={"code": "lib", "name": "مكتبة",
                                                               "permissions": ["library.read", "library.manage"]})
    _make_user(tenant_a, client, "lib1", "lib")
    r = client.delete(f"/api/v1/library/systems/{own['id']}", headers=tenant_a.headers("lib1", "user-pass-123"))
    assert r.status_code == 403 and r.json()["error"]["details"]["permission"] == "library.delete"
    assert client.delete(f"/api/v1/library/systems/{own['id']}", headers=tenant_a.h).json()["result"] == "deleted"


def test_print_any_screen(tenant_a, client):
    r = client.post("/api/v1/documents/report", headers=tenant_a.h, json={
        "title": "العملاء", "subtitle": "بحث: أحمد", "sections": [
            {"title": "القائمة", "columns": ["الاسم", "الرصيد"], "rows": [["<script>x</script>", "1,200.00"], ["محمد"]],
             "nums": [1]},
            {"kv": [["الهاتف", "0100"]]}]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "العملاء" in html and "بحث: أحمد" in html and "1,200.00" in html and "الهاتف" in html
    assert "<script>x" not in html and "&lt;script&gt;" in html            # what the screen sends is escaped
    assert "size: A4;" in html                                             # portrait for few columns
    wide = client.post("/api/v1/documents/report", headers=tenant_a.h, json={
        "title": "x", "sections": [{"columns": [str(i) for i in range(9)], "rows": []}]}).text
    assert "A4 landscape" in wide
