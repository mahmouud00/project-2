from decimal import Decimal as D

from app.modules.sales.pricing import money

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
    pl = None                              # price lists are gone: the salesperson types the price
    customer = client.post("/api/v1/customers", headers=h, json={"name": "أحمد محمد", "phone": "01012345678",
                                                                "address": "القاهرة"}).json()
    return lib, branch, pl, customer


def price_at_top(client, h, q):
    """The salesperson types a price on every line without one: the top of the guide."""
    for line in q["lines"]:
        if not line["priced"]:
            r = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=h,
                             json={"version": line["version"], "manual_unit_price": line["top_unit_price"]})
            assert r.status_code == 200, r.text
            q = r.json()
    return q


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
    assert len(q["lines"]) == 2 and q["price_list_id"] is None
    line = q["lines"][0]
    assert D(line["unit_cost"]) > 0 and line["cost_breakdown"]["missing_costs"] == []
    # the guide: fair = cost + 20 %, top = cost + 30 %; no price until the salesperson types one
    assert D(line["fair_unit_price"]) == money(D(line["unit_cost"]) * D("1.2"))
    assert D(line["top_unit_price"]) == money(D(line["unit_cost"]) * D("1.3"))
    assert D(line["unit_price"]) == 0 and not line["priced"] and q["unpriced_lines"] == 2
    r = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "sent"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUOTE_UNPRICED"
    q = price_at_top(client, h, q)
    line = q["lines"][0]
    assert D(line["unit_price"]) == D(line["top_unit_price"]) and D(q["top_total"]) == D(q["subtotal"])
    assert D(q["tax_pct"]) == 14 and D(q["total"]) == money(D(q["subtotal"]) * D("1.14"))
    assert line["formula_set_version_id"] == lib["version"]["id"]

    q = price_at_top(client, h, q)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "sent"}).json()
    q = price_at_top(client, h, q)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h,
                    json={"version": q["version"], "status": "accepted"}).json()
    assert client.post(f"/api/v1/quotations/{q['id']}/lines", headers=h, json={
        "model_id": model_id, "opening_width_mm": 900, "opening_height_mm": 900}).status_code == 409

    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]})
    assert wo.status_code == 201, wo.text
    wo = wo.json()
    assert wo["stage"] == "quotation" and D(wo["deposit_required"]) == (D(q["total"]) * D("0.3")).quantize(D("0.01"))
    r = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h, json={"version": wo["version"], "to": "approved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SALE_NOT_APPROVED"
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/approve-sale", headers=h, json={"version": wo["version"]}).json()
    assert wo["sale_status"] == "approved"
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

    outputs = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h).json()
    needed = {c["sku"]: D(c["qty"]) for c in outputs["costs"] if c["type"] != "glass"}
    assert set(needed) == {f"{code}-FRAME-W", f"{code}-SASH-W", f"{code}-HANDLE-W", f"{code}-WHEEL-W"}
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/stage", headers=h,
                     json={"version": wo["version"], "to": "manufacturing"})
    assert wo.status_code == 200, wo.text      # no warehouse: the goods are bought per order
    wo = wo.json()

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
    assert client.get("/api/v1/customers", headers=hb).json()["total"] == 0


def test_impossible_opening_rejected_in_quote(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "TINY")
    r = client.post("/api/v1/quotations", headers=tenant_a.h, json={
        "customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 150, "opening_height_mm": 150}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CALC_INVALID"


def test_purchasing_and_treasury(platform, tenant_a, client):
    code = "PUR"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد القطاعات"}).json()
    sku = f"{code}-FRAME-W"
    po = client.post("/api/v1/purchase-orders", headers=h, json={
        "supplier_id": sup["id"], "branch_id": branch["id"],
        "lines": [{"sku": sku, "qty": "60", "unit_cost": "120"}]}).json()
    assert D(po["total"]) == D("7200.00") and po["status"] == "draft"
    # nobody orders it before the accounts confirm it
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/status", headers=h, json={"version": po["version"],
                                                                                   "status": "ordered"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PO_NOT_APPROVED"
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=h,
                     json={"version": po["version"], "note": "تمام"}).json()
    assert po["status"] == "approved" and po["approved_at"] and po["approval_note"] == "تمام"
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/status", headers=h, json={"version": po["version"],
                                                                                    "status": "ordered"}).json()
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=h, json={
        "version": po["version"], "lines": [{"line_id": po["lines"][0]["id"], "qty": "40"}]}).json()
    assert po["status"] == "partial"
    got = client.get(f"/api/v1/purchase-orders/{po['id']}", headers=h).json()
    assert got["number"] == po["number"] and D(got["lines"][0]["received_qty"]) == 40
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=h, json={
        "version": po["version"], "lines": [{"line_id": po["lines"][0]["id"], "qty": "30"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVER_RECEIPT"
    # last purchase price became the company cost for quotes
    calc_cost = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "lines": [{
            "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6"}]}).json()["lines"][0]["cost_breakdown"]["lines"]
    assert next(l for l in calc_cost if l["sku"] == sku)["unit_cost"] == "120.0000"

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
