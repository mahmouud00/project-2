from decimal import Decimal as D

from tests.library_helpers import build_library


def _setup(client, platform, tenant, code):
    lib = build_library(client, platform, code=code)
    r = client.post("/api/v1/library/materials", headers=platform.h, json={
        "code": f"{code}-GLASS6", "name": "زجاج 6 مم", "kind": "glass", "unit": "m2", "reference_cost": "300"})
    assert r.status_code == 201, r.text
    h = tenant.h
    company = client.get("/api/v1/company", headers=h).json()
    r = client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        "default_tax_pct": "14", "deposit_pct": "30", "saw_kerf_mm": "4", "bar_trim_mm": "10",
        "min_reusable_offcut_mm": "500", "quote_waste_pct": "10"}})
    assert r.status_code == 200, r.text
    branch = client.get("/api/v1/branches", headers=h).json()["items"][0]
    pl = client.post("/api/v1/price-lists", headers=h, json={"code": "END", "name": "عميل نهائي",
                                                            "customer_type": "end", "margin_pct": "25"}).json()
    customer = client.post("/api/v1/customers", headers=h, json={"name": "أحمد محمد", "phone": "01012345678",
                                                                "address": "القاهرة"}).json()
    return lib, branch, pl, customer


def test_full_cycle(platform, tenant_a, tenant_b, client):
    code = "FLOW"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    model_id = lib["model"]["id"]

    survey = client.post("/api/v1/surveys", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "address": "القاهرة", "openings": [
            {"location": "صالة", "opening_width_mm": 1500, "opening_height_mm": 1200, "model_id": model_id,
             "params": {"leaf_count": 2}, "color_code": "W", "glass_material_code": f"{code}-GLASS6", "qty": 2},
            {"location": "مطبخ", "opening_width_mm": 1000, "opening_height_mm": 1000, "model_id": model_id,
             "color_code": "W", "glass_material_code": f"{code}-GLASS6"}]})
    assert survey.status_code == 201, survey.text
    survey = survey.json()

    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "survey_id": survey["id"]})
    assert q.status_code == 201, q.text
    q = q.json()
    assert len(q["lines"]) == 2 and q["price_list_id"] == pl["id"]
    line = q["lines"][0]
    assert D(line["unit_cost"]) > 0 and line["cost_breakdown"]["missing_costs"] == []
    assert D(line["unit_price"]) == (D(line["unit_cost"]) * D("1.25")).quantize(D("0.01"))
    assert D(q["tax_pct"]) == 14 and D(q["total"]) == (D(q["subtotal"]) * D("1.14")).quantize(D("0.01"))
    assert line["formula_set_version_id"] == lib["version"]["id"]

    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "sent"}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h,
                    json={"version": q["version"], "status": "accepted"}).json()
    assert client.post(f"/api/v1/quotations/{q['id']}/lines", headers=h, json={
        "model_id": model_id, "opening_width_mm": 900, "opening_height_mm": 900}).status_code == 409

    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]})
    assert wo.status_code == 201, wo.text
    wo = wo.json()
    assert wo["stage"] == "quotation" and D(wo["deposit_required"]) == (D(q["total"]) * D("0.3")).quantize(D("0.01"))
    r = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": "approved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEPOSIT_REQUIRED"

    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "CASH1", "name": "خزينة", "branch_id": branch["id"]}).json()
    tx = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": wo["deposit_required"], "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"]})
    assert tx.status_code == 201, tx.text
    wo = client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()
    assert D(wo["paid_amount"]) == D(wo["deposit_required"])
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h,
                     json={"version": wo["version"], "to": "approved"}).json()
    assert wo["stage"] == "approved"

    # warehouse with opening stock
    wh = client.post("/api/v1/warehouses", headers=h, json={"code": "MAIN", "name": "مخزن", "branch_id": branch["id"]}).json()
    outputs = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h).json()
    needed = {c["sku"]: D(c["qty"]) for c in outputs["costs"] if c["type"] != "glass"}
    assert set(needed) == {f"{code}-FRAME-W", f"{code}-SASH-W", f"{code}-HANDLE-W", f"{code}-WHEEL-W"}
    r = client.post("/api/v1/inventory/adjustments", headers=h, json={
        "warehouse_id": wh["id"], "reason": "رصيد افتتاحي",
        "lines": [{"sku": sku, "qty": str(q * 2), "unit_cost": "100"} for sku, q in needed.items()]})
    assert r.status_code == 201, r.text
    wo = client.patch(f"/api/v1/work-orders/{wo['id']}", headers=h, json={"version": wo["version"],
                                                                          "warehouse_id": wh["id"]}).json()
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h,
                     json={"version": wo["version"], "to": "manufacturing"})
    assert wo.status_code == 200, wo.text
    wo = wo.json()
    assert wo["materials_issued"] is True
    bal = {b["sku"]: D(b["qty"]) for b in client.get(f"/api/v1/inventory/balances?warehouse_id={wh['id']}",
                                                       headers=h).json()}
    assert all(bal[sku] == q for sku, q in needed.items())  # half consumed

    out = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h).json()
    frame = next(c for c in out["cut_list"] if c["sku"] == f"{code}-FRAME-W")
    assert frame["total_pieces"] == 12  # (2 openings x qty 2 + 1) ... 3 windows x 4 frame pieces
    plan = next(p for p in out["optimisation"] if p["sku"] == f"{code}-FRAME-W")
    assert plan["bars_count"] >= 1 and D(plan["waste_pct"]) >= 0
    assert len(out["glass"]) == 2 and out["glass"][0]["material_code"] == f"{code}-GLASS6"
    assert {a["sku"] for a in out["accessories"]} == {f"{code}-HANDLE-W", f"{code}-WHEEL-W"}
    assert D(out["material_cost_total"]) > 0 and out["missing_costs"] == []
    assert out["drawings"][0]["model_image_id"] == lib["image"]["id"] and out["drawings"][0]["elements"]
    assert client.post(f"/api/v1/work-orders/{wo['id']}/manufacturing/generate", headers=h).status_code == 409

    for stage in ("assembly", "quality", "delivered"):
        wo = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h,
                         json={"version": wo["version"], "to": stage}).json()
    assert wo["stage"] == "delivered" and [l["to_stage"] for l in wo["stage_log"]][-3:] == ["assembly", "quality",
                                                                                              "delivered"]
    r = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": "cancelled"})
    assert r.status_code == 409

    stmt = client.get(f"/api/v1/customers/{customer['id']}/statement", headers=h).json()
    assert D(stmt["paid"]) == D(wo["deposit_required"])

    # another company sees nothing of it
    hb = tenant_b.h
    assert client.get(f"/api/v1/customers/{customer['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/quotations/{q['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/work-orders/{wo['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=hb).status_code == 404
    assert client.get(f"/api/v1/inventory/balances?warehouse_id={wh['id']}", headers=hb).status_code == 404
    assert client.get("/api/v1/customers", headers=hb).json()["total"] == 0


def test_insufficient_stock_blocks_manufacturing(platform, tenant_a, client):
    code = "NOSTK"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "lines": [{
            "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6"}]}).json()
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h,
                     json={"quotation_id": q["id"], "deposit_required": "0"}).json()
    wh = client.post("/api/v1/warehouses", headers=h, json={"code": "W2", "name": "w", "branch_id": branch["id"]}).json()
    wo = client.patch(f"/api/v1/work-orders/{wo['id']}", headers=h, json={"version": wo["version"],
                                                                          "warehouse_id": wh["id"]}).json()
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": "approved"}).json()
    r = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": "manufacturing"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()["stage"] == "approved"


def test_impossible_opening_rejected_in_quote(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "TINY")
    r = client.post("/api/v1/quotations", headers=tenant_a.h, json={
        "customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 150, "opening_height_mm": 150}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CALC_INVALID"


def test_purchasing_transfers_and_treasury(platform, tenant_a, client):
    code = "PUR"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    b2 = client.post("/api/v1/branches", headers=h, json={"code": "SHOW", "name": "معرض", "kind": "showroom"}).json()
    wh1 = client.post("/api/v1/warehouses", headers=h, json={"code": "PW1", "name": "1", "branch_id": branch["id"]}).json()
    wh2 = client.post("/api/v1/warehouses", headers=h, json={"code": "PW2", "name": "2", "branch_id": b2["id"]}).json()
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد القطاعات"}).json()
    sku = f"{code}-FRAME-W"
    po = client.post("/api/v1/purchase-orders", headers=h, json={
        "supplier_id": sup["id"], "branch_id": branch["id"], "warehouse_id": wh1["id"],
        "lines": [{"sku": sku, "qty": "60", "unit_cost": "120"}]}).json()
    assert D(po["total"]) == D("7200.00")
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/status", headers=h, json={"version": po["version"],
                                                                                    "status": "ordered"}).json()
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=h, json={
        "version": po["version"], "lines": [{"line_id": po["lines"][0]["id"], "qty": "40"}]}).json()
    assert po["status"] == "partial"
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=h, json={
        "version": po["version"], "lines": [{"line_id": po["lines"][0]["id"], "qty": "30"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVER_RECEIPT"
    # last purchase price became the company cost for quotes
    calc_cost = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "lines": [{
            "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6"}]}).json()["lines"][0]["cost_breakdown"]["lines"]
    assert next(l for l in calc_cost if l["sku"] == sku)["unit_cost"] == "120.0000"

    t = client.post("/api/v1/inventory/transfers", headers=h, json={
        "from_warehouse_id": wh1["id"], "to_warehouse_id": wh2["id"], "lines": [{"sku": sku, "qty": "15"}]}).json()
    t = client.post(f"/api/v1/inventory/transfers/{t['id']}/send", headers=h, json={"version": t["version"]}).json()
    t = client.post(f"/api/v1/inventory/transfers/{t['id']}/receive", headers=h, json={"version": t["version"]}).json()
    assert t["status"] == "received"
    b1 = client.get(f"/api/v1/inventory/balances?warehouse_id={wh1['id']}", headers=h).json()
    b2b = client.get(f"/api/v1/inventory/balances?warehouse_id={wh2['id']}", headers=h).json()
    assert D(b1[0]["qty"]) == 25 and D(b2b[0]["qty"]) == 15

    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "PB", "name": "b", "branch_id": branch["id"]}).json()
    r = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "out", "amount": "1000", "party_type": "supplier", "party_id": sup["id"],
        "purchase_order_id": po["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_CASH"
    client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "5000", "party_type": "other"})
    pay = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "out", "amount": "1000", "party_type": "supplier", "party_id": sup["id"],
        "purchase_order_id": po["id"]}).json()
    st = client.get(f"/api/v1/suppliers/{sup['id']}/statement", headers=h).json()
    assert D(st["received_value"]) == D("4800.00") and D(st["paid"]) == 1000 and D(st["balance"]) == D("3800.00")
    rev = client.post(f"/api/v1/cash-transactions/{pay['id']}/reverse", headers=h, json={"note": "خطأ"})
    assert rev.status_code == 201
    assert client.post(f"/api/v1/cash-transactions/{pay['id']}/reverse", headers=h, json={"note": "x"}).status_code == 409
    assert D(client.get(f"/api/v1/suppliers/{sup['id']}/statement", headers=h).json()["paid"]) == 0
    assert D(next(c for c in client.get("/api/v1/cashboxes", headers=h).json() if c["id"] == box["id"])["balance"]) == 5000


def test_branch_scoped_user_sees_only_branch(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "BR")
    h = tenant_a.h
    b2 = client.post("/api/v1/branches", headers=h, json={"code": "B2X", "name": "فرع 2"}).json()
    roles = {r["code"]: r for r in client.get("/api/v1/roles", headers=h).json()}
    client.post("/api/v1/users", headers=h, json={"username": "sales_b2", "password": "user-pass-123", "full_name": "s",
                                                  "assignments": [{"role_id": roles["sales"]["id"], "branch_id": b2["id"]}]})
    hs = tenant_a.headers("sales_b2", "user-pass-123")
    r = client.post("/api/v1/surveys", headers=hs, json={"customer_id": customer["id"], "branch_id": branch["id"]})
    assert r.status_code == 403
    r = client.post("/api/v1/surveys", headers=hs, json={"customer_id": customer["id"], "branch_id": b2["id"]})
    assert r.status_code == 201
    client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"]})
    surveys = client.get("/api/v1/surveys", headers=hs).json()["items"]
    assert surveys and all(s["branch_id"] == b2["id"] for s in surveys)


def test_pii_access_is_logged(tenant_a, client):
    h = tenant_a.h
    c = client.post("/api/v1/customers", headers=h, json={"name": "سارة", "phone": "01099999999"}).json()
    client.get(f"/api/v1/customers/{c['id']}", headers=h)
    from app.db.session import tenant_session
    from app.modules.org.models import PiiAccessLog
    from sqlalchemy import select
    with tenant_session(tenant_a.id) as db:
        actions = [l.action for l in db.scalars(select(PiiAccessLog).where(PiiAccessLog.subject_id == c["id"]))]
    assert "create" in actions and "view" in actions
