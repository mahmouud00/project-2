from decimal import Decimal as D

from tests.library_helpers import PNG
from tests.test_business_flow import _setup, price_at_top
from tests.orders import order


def _order(client, platform, tenant, code):
    lib, branch, pl, customer = _setup(client, platform, tenant, code)
    h = tenant.h
    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "discount_amount": "100", "lines": [
            {"location": "صالة", "model_id": lib["model"]["id"], "opening_width_mm": 1800, "opening_height_mm": 1400,
             "qty": 2, "color_code": "W", "glass_material_code": f"{code}-GLASS6", "params": {"leaf_count": 2}},
            {"location": "مطبخ", "model_id": lib["model"]["id"], "opening_width_mm": 1200, "opening_height_mm": 1000,
             "color_code": "W", "glass_material_code": f"{code}-GLASS6"}]}).json()
    q = price_at_top(client, h, q)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = order(client, h, q)
    return lib, branch, customer, q, wo


def test_invoice_first_discounts_collections_then_work_order(platform, tenant_a, client):
    from tests.orders import cashbox, collect
    from tests.test_org_permissions_locking import _make_user

    lib, branch, pl, customer = _setup(client, platform, tenant_a, "INV1")
    h = tenant_a.h
    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "discount_amount": "100", "lines": [
            {"location": "صالة", "model_id": lib["model"]["id"], "opening_width_mm": 1800, "opening_height_mm": 1400,
             "qty": 2, "color_code": "W", "glass_material_code": "INV1-GLASS6", "params": {"leaf_count": 2}},
            {"location": "مطبخ", "model_id": lib["model"]["id"], "opening_width_mm": 1200, "opening_height_mm": 1000,
             "color_code": "W", "glass_material_code": "INV1-GLASS6"}]}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    # no work order straight from the quotation: through its invoice
    r = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "WO_FROM_INVOICE"
    inv = client.post("/api/v1/invoices", headers=h, json={"quotation_id": q["id"]})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    assert inv["status"] == "draft" and inv["number"] is None and len(inv["lines"]) == 2
    first = inv["lines"][0]
    assert first["model_name"] and first["width_mm"] and first["drawing"]
    assert D(inv["total"]) == D(q["total"])            # same as the accepted quotation
    # per-line discount + extra service line
    r = client.patch(f"/api/v1/invoice-lines/{first['id']}", headers=h, json={"version": first["version"], "discount_pct": "10"})
    assert r.status_code == 200
    inv = client.post(f"/api/v1/invoices/{inv['id']}/lines", headers=h, json={
        "kind": "service", "description": "تركيب", "qty": "1", "unit_price": "500"}).json()
    gross = D(first["unit_price"]) * D(first["qty"])
    assert D(inv["lines"][0]["discount_amount"]) == (gross * D("0.1")).quantize(D("0.01"))
    taxable = D(inv["lines_total"]) - D(inv["discount_amount"])
    assert D(inv["total"]) == (taxable * (1 + D(inv["tax_pct"]) / 100)).quantize(D("0.01"))
    # money only on an issued invoice
    assert client.post(f"/api/v1/invoices/{inv['id']}/collections", headers=h, json={"amount": "10"}).status_code == 409
    inv = client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=h, json={"version": inv["version"]}).json()
    assert inv["status"] == "issued" and inv["number"].startswith("INV-")
    r = client.post(f"/api/v1/invoices/{inv['id']}/lines", headers=h, json={"description": "x", "unit_price": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVOICE_LOCKED"
    from app.modules.sales.pricing import money
    assert D(inv["deposit_amount"]) == money(D(inv["total"]) * D("0.3")) and D(inv["collected_pct"]) == 0

    # customer money comes in through the invoice only
    box = cashbox(client, h, branch["id"])
    r = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "1000", "party_type": "customer",
        "party_id": customer["id"], "invoice_id": inv["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "COLLECT_ON_INVOICE"
    # the salesperson records it: nothing counts until the accounts confirm
    seller = _make_user(tenant_a, client, "seller_inv", "sales")
    client.post(f"/api/v1/customers/{customer['id']}/transfer", headers=h, json={"to_user_id": seller["id"]})
    hs = tenant_a.headers("seller_inv", "user-pass-123")
    c = client.post(f"/api/v1/invoices/{inv['id']}/collections", headers=hs, json={"amount": "1000", "method": "transfer",
                                                                                 "reference": "TRX-1"}).json()
    assert c["status"] == "pending"
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert D(inv["paid_amount"]) == 0 and D(inv["pending_amount"]) == 1000
    big = client.post(f"/api/v1/invoices/{inv['id']}/collections", headers=hs, json={"amount": inv["total"]})
    assert big.status_code == 422 and big.json()["error"]["code"] == "COLLECTION_TOO_LARGE"
    r = client.post(f"/api/v1/invoices/{inv['id']}/work-order", headers=h, json={"version": inv["version"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEPOSIT_REQUIRED"
    r = client.post(f"/api/v1/collections/{c['id']}/reject", headers=h, json={"version": c["version"], "reason": "مش واصل"})
    assert r.json()["status"] == "rejected"
    collect(client, hs, inv, inv["deposit_amount"], box=box, confirm_h=h)
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert D(inv["paid_amount"]) == D(inv["deposit_amount"]) and D(inv["pending_amount"]) == 0
    assert D(inv["collected_pct"]) == (D(inv["paid_amount"]) * 100 / D(inv["total"])).quantize(D("0.1"))
    # the deposit is in: the invoice becomes a work order, the sale confirmed, its money with it
    wo = client.post(f"/api/v1/invoices/{inv['id']}/work-order", headers=h, json={"version": inv["version"]})
    assert wo.status_code == 200, wo.text
    wo = wo.json()
    assert wo["sale_status"] == "approved" and D(wo["paid_amount"]) == D(inv["paid_amount"]) and wo["quotation_id"] == q["id"]
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert inv["work_order_id"] == wo["id"]
    # later money: on the invoice still, and on its work order
    collect(client, hs, inv, "1000", box=box, confirm_h=h)
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert D(inv["paid_amount"]) == D(inv["deposit_amount"]) + 1000
    assert D(client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()["paid_amount"]) == D(inv["paid_amount"])
    assert [x["status"] for x in client.get(f"/api/v1/invoices/{inv['id']}/collections", headers=hs).json()] == \
        ["rejected", "confirmed", "confirmed"]
    # the customer statement bills the issued invoice (with its service line)
    st = client.get(f"/api/v1/customers/{customer['id']}/statement", headers=h).json()
    assert D(st["billed"]) == D(inv["total"]) and D(st["balance"]) == D(inv["balance"])
    assert st["orders"][0]["invoiced"] is True and st["invoices"][0]["number"] == inv["number"]

    html = client.get(f"/api/v1/invoices/{inv['id']}/print", headers=h)
    assert html.status_code == 200 and "text/html" in html.headers["content-type"]
    body = html.text
    assert inv["number"] in body and "فاتورة" in body and "<svg" in body and "180" in body and "عرض × ارتفاع" in body
    assert "@font-face" in body


def test_manual_invoice_and_isolation(platform, tenant_a, tenant_b, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "INV2")
    h = tenant_a.h
    inv = client.post("/api/v1/invoices", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "tax_pct": "0", "discount_amount": "50",
        "lines": [{"kind": "service", "description": "صيانة", "qty": "2", "unit_price": "300", "discount_pct": "5"}]}).json()
    assert D(inv["lines_total"]) == D("570.00") and D(inv["total"]) == D("520.00")
    r = client.patch(f"/api/v1/invoices/{inv['id']}", headers=h, json={"version": inv["version"], "discount_amount": "9999"})
    assert r.status_code == 422
    assert client.get(f"/api/v1/invoices/{inv['id']}", headers=tenant_b.h).status_code == 404
    assert client.get(f"/api/v1/invoices/{inv['id']}/print", headers=tenant_b.h).status_code == 404


def test_branding_logo_and_documents(platform, tenant_a, client):
    lib, branch, customer, q, wo = _order(client, platform, tenant_a, "BRD")
    h = tenant_a.h
    company = client.get("/api/v1/company", headers=h).json()
    s = company["settings"] | {"display_name": "مصنع النور للألوميتال", "phone": "0223456789", "tax_number": "123-456-789",
                               "address": "المنطقة الصناعية", "invoice_footer": "شكرًا لتعاملكم معنا", "accent_color": "#0E7490"}
    r = client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": s})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/company/logo", headers=h, files={"file": ("logo.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json()["has_logo"]
    assert client.get("/api/v1/company/logo", headers=h).content == PNG
    pub = client.get(f"/api/v1/system/branding?company_code={tenant_a.code}").json()
    assert pub["name"] == "مصنع النور للألوميتال" and pub["has_logo"] and "tax_number" not in pub
    assert client.get(f"/api/v1/system/branding/logo?company_code={tenant_a.code}").content == PNG
    # settings save keeps the logo
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": company["settings"] | {"logo_media_id": None}})
    assert client.get("/api/v1/company", headers=h).json()["branding"]["has_logo"]

    qh = client.get(f"/api/v1/quotations/{q['id']}/print", headers=h).text
    assert "مصنع النور للألوميتال" in qh and "data:image/png;base64" in qh and "123-456-789" in qh and q["number"] in qh
    ch = client.get(f"/api/v1/work-orders/{wo['id']}/print/cut-list", headers=h).text
    assert "كشف تقطيع" in ch and wo["number"] in ch and "<svg" in ch
    gh = client.get(f"/api/v1/work-orders/{wo['id']}/print/glass", headers=h)
    assert gh.status_code == 200 and "طلبية زجاج" in gh.text and "إجمالي الأمتار لكل نوع زجاج" in gh.text
    assert "كشف تقطيع" not in gh.text and "خطة الأعواد" not in gh.text


def test_print_shows_width_before_height(platform, tenant_a, client):
    from app.modules.documents.render import size
    assert str(size(1800, 1400)) == '<span class="dim"><b>180</b><span class="x">×</span>140</span>'
