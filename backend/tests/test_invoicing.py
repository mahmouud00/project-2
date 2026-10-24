from decimal import Decimal as D

from tests.library_helpers import PNG
from tests.test_business_flow import _setup


def _order(client, platform, tenant, code):
    lib, branch, pl, customer = _setup(client, platform, tenant, code)
    h = tenant.h
    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "discount_amount": "100", "lines": [
            {"location": "صالة", "model_id": lib["model"]["id"], "opening_width_mm": 1800, "opening_height_mm": 1400,
             "qty": 2, "color_code": "W", "glass_material_code": f"{code}-GLASS6", "params": {"leaf_count": 2}},
            {"location": "مطبخ", "model_id": lib["model"]["id"], "opening_width_mm": 1200, "opening_height_mm": 1000,
             "color_code": "W", "glass_material_code": f"{code}-GLASS6"}]}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    return lib, branch, customer, q, wo


def test_invoice_from_work_order_with_discounts_and_payment(platform, tenant_a, client):
    lib, branch, customer, q, wo = _order(client, platform, tenant_a, "INV1")
    h = tenant_a.h
    inv = client.post("/api/v1/invoices", headers=h, json={"work_order_id": wo["id"]})
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
    # a second invoice for the same order is refused
    assert client.post("/api/v1/invoices", headers=h, json={"work_order_id": wo["id"]}).status_code == 409

    inv = client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=h, json={"version": inv["version"]}).json()
    assert inv["status"] == "issued" and inv["number"].startswith("INV-")
    r = client.post(f"/api/v1/invoices/{inv['id']}/lines", headers=h, json={"description": "x", "unit_price": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVOICE_LOCKED"

    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "IC", "name": "c", "branch_id": branch["id"]}).json()
    r = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "1000", "party_type": "customer",
        "party_id": customer["id"], "invoice_id": inv["id"]})
    assert r.status_code == 201 and r.json()["work_order_id"] == wo["id"]
    inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert D(inv["paid_amount"]) == 1000 and D(inv["balance"]) == D(inv["total"]) - 1000
    assert D(client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()["paid_amount"]) == 1000

    html = client.get(f"/api/v1/invoices/{inv['id']}/print", headers=h)
    assert html.status_code == 200 and "text/html" in html.headers["content-type"]
    body = html.text
    assert inv["number"] in body and "فاتورة" in body and "<svg" in body and "180" in body and "عرض × ارتفاع" in body
    assert "@font-face" in body
    r = client.post(f"/api/v1/invoices/{inv['id']}/cancel", headers=h, json={"version": inv["version"], "reason": "خطأ في البيانات"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


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


def test_print_shows_width_before_height(platform, tenant_a, client):
    from app.modules.documents.render import size
    assert str(size(1800, 1400)) == '<span class="dim"><b>180</b><span class="x">×</span>140</span>'
