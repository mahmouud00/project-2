"""التسعير الأوتوماتيك: the quotation prices itself (the whole cost + the company's one margin, over the billed m²,
rounded up to 10, the same on every window). The salesperson cannot change it or see the cost; he asks for a discount
and the sales manager decides (his own price per m², a discount amount or a percentage). Any change to the openings
takes the price back to automatic. A quotation is accepted only for a customer with a national ID."""
import re
from decimal import Decimal as D

from tests.customers import cust as new_customer
from tests.test_business_flow import _setup
from tests.test_org_permissions_locking import _make_user


def _status(client, h, q, status):
    return client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": status})


def _ceil10(x: D) -> D:
    return (x / 10).to_integral_value(rounding="ROUND_CEILING") * 10


def test_automatic_price_discount_request_and_the_sales_manager(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "AUTO")
    h = tenant_a.h
    company = client.get("/api/v1/company", headers=h).json()
    assert client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        **company["settings"], "labor_cost_per_m2": "100", "fair_margin_pct": "25"}}).status_code == 200
    _make_user(tenant_a, client, "seller_auto", "sales", branch["id"])
    _make_user(tenant_a, client, "manager_auto", "sales_manager", branch["id"])
    seller = tenant_a.headers("seller_auto", "user-pass-123")
    manager = tenant_a.headers("manager_auto", "user-pass-123")
    window = {"model_id": lib["model"]["id"], "color_code": "W", "glass_material_code": "AUTO-GLASS6"}
    q = client.post("/api/v1/quotations", headers=seller, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{**window, "opening_width_mm": 1000, "opening_height_mm": 2000, "qty": 2},
                  {**window, "opening_width_mm": 700, "opening_height_mm": 800}]})
    assert q.status_code == 201, q.text
    q = q.json()

    # the salesperson sees prices only
    assert q["total_cost"] is None and all(l["unit_cost"] is None and "lines" not in l["cost_breakdown"]
                                          for l in q["lines"])
    full = client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()          # the administrator sees the cost
    units = full["lines"]
    cost = sum(D(l["unit_cost"]) * l["qty"] for l in units)
    billed = sum(D(l["billed_area_m2"]) * l["qty"] for l in units)
    assert billed == D("5")                                                       # 2 × 2 m² + 1 m² (minimum)
    ppm = _ceil10(cost * D("1.25") / billed)
    assert D(q["auto_price_per_m2"]) == D(q["price_per_m2"]) == ppm
    assert all(D(l["price_per_m2"]) == ppm for l in q["lines"]) and D(q["subtotal"]) == ppm * 5
    listed = client.get("/api/v1/quotations", headers=seller).json()["items"]
    assert all(x["total_cost"] is None for x in listed)

    # he cannot change the price or give a discount
    r = client.post(f"/api/v1/quotations/{q['id']}/price-per-m2", headers=seller,
                    json={"version": q["version"], "price_per_m2": "100"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PRICE_BY_MANAGER"
    r = client.patch(f"/api/v1/quotations/{q['id']}", headers=seller, json={"version": q["version"], "discount_amount": "50"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PRICE_BY_MANAGER"
    assert client.post(f"/api/v1/quotations/{q['id']}/manager-price", headers=seller,
                       json={"version": q["version"], "discount_pct": "5"}).status_code == 403
    line = q["lines"][0]
    q = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=seller,    # a typed price is ignored
                     json={"version": line["version"], "manual_unit_price": "1"}).json()
    assert D(q["subtotal"]) == ppm * 5

    # he asks for a discount: the sales manager is told
    q = client.post(f"/api/v1/quotations/{q['id']}/request-discount", headers=seller, json={"note": "عميل قديم"}).json()
    assert q["discount_requested_at"] and q["discount_request_note"] == "عميل قديم"
    inbox = client.get("/api/v1/notifications", headers=manager).json()["items"]
    assert any("طلب خصم" in n["title"] and q["number"] in n["title"] for n in inbox)

    # the manager gives 10 %: the salesperson sees it and is told
    r = client.post(f"/api/v1/quotations/{q['id']}/manager-price", headers=manager,
                    json={"version": q["version"], "discount_pct": "10", "note": "موافق"})
    assert r.status_code == 200, r.text
    q = r.json()
    assert D(q["discount_amount"]) == ppm * 5 / 10 and not q["discount_requested_at"]
    assert D(q["price_approved_total"]) == D(q["net_total"]) == ppm * 5 * D("0.9")
    seen = client.get(f"/api/v1/quotations/{q['id']}", headers=seller).json()
    assert D(seen["discount_amount"]) == D(q["discount_amount"])
    assert any(q["number"] in n["title"] for n in client.get("/api/v1/notifications", headers=seller).json()["items"])
    # or an amount, or his own price per m² (not both kinds of discount)
    r = client.post(f"/api/v1/quotations/{q['id']}/manager-price", headers=manager,
                    json={"version": q["version"], "discount_pct": "5", "discount_amount": "100"})
    assert r.status_code == 422
    q = client.post(f"/api/v1/quotations/{q['id']}/manager-price", headers=manager,
                    json={"version": q["version"], "price_per_m2": "900", "discount_amount": "100"}).json()
    assert D(q["price_per_m2"]) == 900 and D(q["subtotal"]) == 4500 and D(q["net_total"]) == 4400
    assert D(q["auto_price_per_m2"]) == ppm
    r = client.post(f"/api/v1/quotations/{q['id']}/manager-price", headers=manager,
                    json={"version": q["version"], "discount_amount": "99999"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "DISCOUNT_TOO_LARGE"

    # a change to the openings: back to the automatic price, no discount
    q = client.post(f"/api/v1/quotations/{q['id']}/lines", headers=seller,
                    json={**window, "opening_width_mm": 1000, "opening_height_mm": 1000}).json()
    assert q["manager_price_per_m2"] is None and D(q["discount_amount"]) == 0 and q["price_approved_total"] is None
    assert D(q["price_per_m2"]) == D(q["auto_price_per_m2"]) and len(q["lines"]) == 3

    # accepted only with the customer's national ID
    plain = client.post("/api/v1/customers", headers=h, json=new_customer("عميل من غير رقم قومي")).json()
    q2 = client.post("/api/v1/quotations", headers=seller, json={"customer_id": plain["id"], "branch_id": branch["id"],
                                                               "lines": [{**window, "opening_width_mm": 1000,
                                                                          "opening_height_mm": 1000}]}).json()
    r = _status(client, seller, q2, "accepted")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NATIONAL_ID_REQUIRED"
    client.patch(f"/api/v1/customers/{plain['id']}", headers=h,
                 json={"version": plain["version"], "national_id": "29001011234567"})
    assert _status(client, seller, q2, "accepted").status_code == 200


def test_customer_writes_the_national_id_on_the_link(platform, tenant_a, client):
    lib, branch, _, _ = _setup(client, platform, tenant_a, "NID")
    h = tenant_a.h
    plain = client.post("/api/v1/customers", headers=h, json=new_customer("عميل اللينك الجديد")).json()
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": plain["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000,
                   "color_code": "W", "glass_material_code": "NID-GLASS6"}]}).json()
    link = client.post(f"/api/v1/quotations/{q['id']}/share", headers=h, json={"days": 7}).json()
    token = re.search(r"/s/([^/?#]+)", link["url"]).group(1)
    page = client.get(f"/s/{token}", headers={"user-agent": "Mozilla/5.0"}).text
    assert 'name="national_id"' in page
    r = client.post(f"/s/{token}/accept", data={"national_id": "123"}, follow_redirects=False)
    assert r.status_code == 422 and client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()["status"] == "sent"
    r = client.post(f"/s/{token}/accept", data={"national_id": "٢٩٠٠١٠١١٢٣٤٥٦٧"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()["status"] == "accepted"
    assert client.get(f"/api/v1/customers/{plain['id']}", headers=h).json()["national_id"] == "29001011234567"


def test_customer_required_fields(tenant_a, client):
    h = tenant_a.h
    r = client.post("/api/v1/customers", headers=h, json={"name": "أحمد"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CUSTOMER_INCOMPLETE"
    problems = r.json()["error"]["details"]
    assert {"name", "phone", "whatsapp", "governorate", "contact_method", "first_contact",
            "customer_questions"} <= set(problems)
    r = client.post("/api/v1/customers", headers=h, json=new_customer(customer_questions="سؤال واحد"))
    assert r.status_code == 422 and set(r.json()["error"]["details"]) == {"customer_questions"}
    r = client.post("/api/v1/customers", headers=h, json=new_customer(phone="0123"))
    assert set(r.json()["error"]["details"]) == {"phone"}
    r = client.post("/api/v1/customers", headers=h, json=new_customer(governorate="مدينة مش موجودة"))
    assert set(r.json()["error"]["details"]) == {"governorate"}
    # tidied: digits in Arabic and +20 become the local mobile number; questions one per line
    r = client.post("/api/v1/customers", headers=h, json=new_customer(
        "  محمد   علي   حسن ", phone="+20 100 123 4567", whatsapp="٠١٠٠١٢٣٤٥٦٧",
        customer_questions="- سعر المتر؟\n\n- الضمان كام سنة؟"))
    assert r.status_code == 201, r.text
    c = r.json()
    assert (c["name"], c["phone"], c["whatsapp"]) == ("محمد علي حسن", "01001234567", "01001234567")
    assert c["customer_questions"] == "سعر المتر؟\nالضمان كام سنة؟" and c["national_id"] is None
    # an edit cannot clear a required field
    r = client.patch(f"/api/v1/customers/{c['id']}", headers=h, json={"version": c["version"], "whatsapp": ""})
    assert r.status_code == 422
    choices = client.get("/api/v1/customers/choices", headers=h).json()
    assert "القاهرة" in choices["governorates"] and "واتساب" in choices["contact_methods"]
