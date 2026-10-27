"""Survey sheet columns, the guide prices of a survey (fair and top), and the price per m² typed in a quotation."""
from decimal import Decimal as D

from app.modules.sales.pricing import money

from tests.test_arch import _arch_model
from tests.test_business_flow import _setup


def test_survey_sheet_and_price_per_m2(platform, tenant_a, client):
    code = "SQM"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    model_id = lib["model"]["id"]
    glass = f"{code}-GLASS6"
    arch = _arch_model(client, platform, lib, f"{code}-")

    sv = client.post("/api/v1/surveys", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "floor": "الثالث", "technician": "عم سيد",
        "openings": [
            {"location": "صالة", "opening_width_mm": 1500, "opening_height_mm": 1200, "total_height_mm": 1800,
             "top_model_id": arch["id"], "model_id": model_id, "color_code": "W", "glass_material_code": glass, "qty": 2, "unit_kind": "sliding",
             "glass_layers": "double", "glass_color": "فيميه", "screen_type": "pleated", "application": "على الحلق القديم"},
            {"location": "حمام", "opening_width_mm": 800, "opening_height_mm": 900, "model_id": model_id,
             "color_code": "W", "glass_material_code": glass, "unit_kind": "hinged", "glass_layers": "single"},
            {"location": "سلم", "opening_width_mm": 600, "opening_height_mm": 600}]})       # no model yet
    assert sv.status_code == 201, sv.text
    sv = sv.json()
    assert sv["kind"] == "window" and sv["floor"] == "الثالث" and sv["technician"] == "عم سيد"
    o = sv["openings"][0]
    assert (o["unit_kind"], o["glass_layers"], o["screen_type"], D(o["total_height_mm"])) == ("sliding", "double", "pleated", 1800)
    r = client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                        "openings": [{"opening_width_mm": 1, "opening_height_mm": 1,
                                                                      "screen_type": "magic"}]})
    assert r.status_code == 422

    # the guide of the survey: cost, fair (+20 %) and top (+30 %), per m² of the billed area (each unit ≥ 1 m²)
    p = client.get(f"/api/v1/surveys/{sv['id']}/pricing", headers=h).json()
    assert p["priced"] == 2 and p["unpriced"] == 1 and p["openings"][2]["error"] == "OPENING_WITHOUT_MODEL"
    assert (D(p["fair_margin_pct"]), D(p["top_margin_pct"])) == (20, 30)
    big, small = p["openings"][0], p["openings"][1]
    # width × total height (1.5 × 1.8) when the total height is written, else width × height
    assert D(big["area_m2"]) == D("2.7") and D(big["billed_area_m2"]) == D("2.7")
    assert D(small["area_m2"]) == D("0.72") and D(small["billed_area_m2"]) == 1          # minimum 1 m²
    for o in (big, small):
        assert D(o["fair_unit_price"]) == money(D(o["unit_cost"]) * D("1.2"))
        assert D(o["top_unit_price"]) == money(D(o["unit_cost"]) * D("1.3"))
    fair = D(big["fair_unit_price"]) * 2 + D(small["fair_unit_price"])
    top = D(big["top_unit_price"]) * 2 + D(small["top_unit_price"])
    assert D(p["fair_total"]) == fair and D(p["top_total"]) == top and D(p["billed_area_m2"]) == D("6.4")
    assert D(p["cost_total"]) == D(big["unit_cost"]) * 2 + D(small["unit_cost"])
    assert D(p["fair_price_per_m2"]) == (fair / D("6.4")).quantize(D("0.01"))
    assert D(p["top_price_per_m2"]) == (top / D("6.4")).quantize(D("0.01"))
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "survey_id": sv["id"]})
    assert q.status_code == 422 and q.json()["error"]["code"] == "OPENING_WITHOUT_MODEL"
    sv = client.patch(f"/api/v1/surveys/{sv['id']}", headers=h, json={"version": sv["version"], "openings": [
        {k: v for k, v in o.items() if k not in ("id", "position")} for o in sv["openings"][:2]]}).json()
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "survey_id": sv["id"]}).json()
    assert D(q["lines"][0]["total_height_mm"]) == 1800 and D(q["lines"][0]["billed_area_m2"]) == D("2.7")
    assert D(q["lines"][0]["opening_height_mm"]) == 1200          # the unit is still made at the opening size

    # quotation: price per m² typed by the user; the guide stays visible
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": model_id, "opening_width_mm": 1500, "opening_height_mm": 1200, "qty": 2,
                   "color_code": "W", "glass_material_code": glass, "price_per_m2": "1000"},
                  {"model_id": model_id, "opening_width_mm": 800, "opening_height_mm": 900, "color_code": "W",
                   "glass_material_code": glass}]}).json()
    a, b = q["lines"]
    assert D(a["unit_price"]) == D("1800.00") and D(a["line_total"]) == D("3600.00") and a["model_code"]
    assert D(b["billed_area_m2"]) == 1 and D(b["unit_price"]) == 0 and not b["priced"]
    assert D(b["fair_price_per_m2"]) == D(b["fair_unit_price"])      # billed area is 1 m²

    q = client.post(f"/api/v1/quotations/{q['id']}/price-per-m2", headers=h,
                    json={"version": q["version"], "price_per_m2": "1250"}).json()
    assert [D(l["line_total"]) for l in q["lines"]] == [D("4500.00"), D("1250.00")]
    assert D(q["subtotal"]) == D("5750.00")
    r = client.patch(f"/api/v1/quotation-lines/{q['lines'][1]['id']}", headers=h,
                     json={"version": q["lines"][1]["version"], "price_per_m2": None, "manual_unit_price": "900"})
    assert D(r.json()["lines"][1]["unit_price"]) == D("900.00")

    # the company's minimum billed area is a setting
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"],
                                                     "settings": {**company["settings"], "min_billed_area_m2": "0"}})
    p = client.get(f"/api/v1/surveys/{sv['id']}/pricing", headers=h).json()
    assert D(p["openings"][1]["billed_area_m2"]) == D("0.72")


def test_shutter_survey_and_print(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "SHT")
    h = tenant_a.h
    sv = client.post("/api/v1/surveys", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "kind": "shutter", "openings": [
            {"location": "بلكونة", "opening_width_mm": 2400, "opening_height_mm": 2600, "installation_method": "خارجي",
             "motor_type": "سومفي", "color_text": "بيج"}]})
    assert sv.status_code == 201, sv.text
    sv = sv.json()
    assert sv["kind"] == "shutter" and sv["openings"][0]["motor_type"] == "سومفي"
    html = client.get(f"/api/v1/surveys/{sv['id']}/print", headers=h)
    assert html.status_code == 200 and "طريقة التركيب" in html.text and "سومفي" in html.text
    r = client.patch(f"/api/v1/surveys/{sv['id']}", headers=h, json={"version": sv["version"], "kind": None})
    assert r.status_code == 200 and r.json()["kind"] == "shutter"


def test_quotation_print_columns(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "QPR")
    h = tenant_a.h
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": lib["model"]["id"], "opening_width_mm": 800, "opening_height_mm": 900, "qty": 3,
                   "color_code": "W", "glass_material_code": "QPR-GLASS6", "price_per_m2": "1100"}]}).json()
    html = client.get(f"/api/v1/quotations/{q['id']}/print", headers=h).text
    for text in ("رقم النموذج", "مساحة الفتحة", "المساحة الكلية", "نوع وشكل النموذج", "سعر المتر", "التكلفة",
                 lib["model"]["code"], "1,100.00", "3,300.00", "الفعلية 0.72", ">3.00<"):
        assert text in html, text


def test_survey_list_carries_openings(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "SVL")
    h = tenant_a.h
    client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"], "openings": [
        {"opening_width_mm": 1000, "opening_height_mm": 1000}, {"opening_width_mm": 900, "opening_height_mm": 800}]})
    items = client.get(f"/api/v1/surveys?customer_id={customer['id']}", headers=h).json()["items"]
    assert [len(s["openings"]) for s in items] == [2]
