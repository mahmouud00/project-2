"""دليل المبيعات: the fair price (cost + 20 %) is the lowest a salesperson may give; under it the sales manager
approves. Margins and labour per m² are company settings."""
from decimal import Decimal as D

from app.modules.sales.pricing import money

from tests.test_business_flow import _setup
from tests.test_org_permissions_locking import _make_user


def _status(client, h, q, status):
    return client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": status})


def test_price_under_fair_needs_the_sales_manager(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "FAIR")
    h = tenant_a.h
    company = client.get("/api/v1/company", headers=h).json()
    r = client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        **company["settings"], "labor_cost_per_m2": "100", "fair_margin_pct": "25", "top_margin_pct": "40"}})
    assert r.status_code == 200, r.text
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 2000, "qty": 2,
                   "color_code": "W", "glass_material_code": "FAIR-GLASS6"}]}).json()
    line = q["lines"][0]
    materials = sum(D(x["amount"]) for x in line["cost_breakdown"]["lines"])
    assert D(line["cost_breakdown"]["labor"]) == 200                              # 2 m² × 100
    assert abs(D(line["unit_cost"]) - (materials + 200)) < D("0.05")
    fair, top = D(line["fair_unit_price"]), D(line["top_unit_price"])
    assert fair == money(D(line["unit_cost"]) * D("1.25"))
    assert top == money(D(line["unit_cost"]) * D("1.40"))
    assert D(q["fair_total"]) == fair * 2 and D(q["top_total"]) == top * 2

    # a salesperson (no approval permission) prices under the fair price
    _make_user(tenant_a, client, "seller_fair", "sales", branch["id"])
    _make_user(tenant_a, client, "manager_fair", "sales_manager", branch["id"])
    seller = tenant_a.headers("seller_fair", "user-pass-123")
    manager = tenant_a.headers("manager_fair", "user-pass-123")
    low = (fair - 50).quantize(D("0.01"))
    q = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=seller,
                     json={"version": line["version"], "manual_unit_price": str(low)}).json()
    assert q["needs_price_approval"] and D(q["net_total"]) == low * 2
    r = _status(client, seller, q, "sent")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PRICE_APPROVAL_REQUIRED"
    assert client.post(f"/api/v1/quotations/{q['id']}/approve-price", headers=seller,
                       json={"version": q["version"]}).status_code == 403
    r = client.post(f"/api/v1/quotations/{q['id']}/request-price-approval", headers=seller)
    assert r.status_code == 200
    inbox = client.get("/api/v1/notifications", headers=manager).json()
    assert any(q["number"] in n["title"] for n in inbox["items"])

    q = client.post(f"/api/v1/quotations/{q['id']}/approve-price", headers=manager,
                    json={"version": q["version"], "note": "عميل قديم"})
    assert q.status_code == 200, q.text
    q = q.json()
    assert not q["needs_price_approval"] and D(q["price_approved_total"]) == low * 2

    # a bigger discount is lower than what was approved: approval again
    q = client.patch(f"/api/v1/quotations/{q['id']}", headers=seller, json={"version": q["version"],
                                                                           "discount_amount": "10"}).json()
    assert q["needs_price_approval"]
    q = client.patch(f"/api/v1/quotations/{q['id']}", headers=seller, json={"version": q["version"],
                                                                           "discount_amount": "0"}).json()
    assert not q["needs_price_approval"]
    assert _status(client, seller, q, "sent").status_code == 200

    # at or above the fair price nobody has to approve
    q2 = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 2000,
                   "color_code": "W", "glass_material_code": "FAIR-GLASS6", "manual_unit_price": str(fair)}]}).json()
    assert not q2["needs_price_approval"] and q2["unpriced_lines"] == 0
    assert client.post(f"/api/v1/quotations/{q2['id']}/approve-price", headers=manager,
                       json={"version": q2["version"]}).json()["error"]["code"] == "PRICE_APPROVAL_NOT_NEEDED"
    assert _status(client, seller, q2, "accepted").status_code == 200
