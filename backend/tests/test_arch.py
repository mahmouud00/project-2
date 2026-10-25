"""Half-circle arch (أرج) above a unit: its own frame and model, calculated at width × (total − height)."""
from decimal import Decimal as D

from app.engine.expr import compile_expr
from tests.test_business_flow import _setup

ARCH = {
    "params": [], "formulas": [{"key": "curve", "label": "طول القوس", "expr": "arc_length(width, height)"}],
    "pieces": [
        {"key": "arch_curve", "label": "حلق مقوس", "element": "حلق الأرج", "role": "frame", "material_code": "{p}FRAME",
         "length_expr": "curve + 2 * weld_allowance", "qty_expr": "1", "angle_left": "90", "angle_right": "90"},
        {"key": "arch_base", "label": "قاعدة الأرج", "element": "حلق الأرج", "side": "width", "role": "frame",
         "material_code": "{p}FRAME", "length_expr": "width", "qty_expr": "1", "angle_left": "90", "angle_right": "90"}],
    "glass": [{"key": "arch_glass", "label": "زجاج الأرج", "width_expr": "width - 2", "height_expr": "height - 1",
               "area_expr": "segment_area(width - 2, height - 1)", "qty_expr": "1"}],
    "accessories": [], "validations": [], "drawing": [],
}


def _arch_model(client, platform, lib, prefix):
    import json
    definition = json.loads(json.dumps(ARCH).replace("{p}", prefix))
    m = client.post("/api/v1/library/models", headers=platform.h, json={
        "system_id": lib["system"]["id"], "code": "ARCH", "name": "أرج نص دايرة", "category": "window",
        "status": "approved", "definition": definition})
    assert m.status_code == 201, m.text
    r = client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=platform.h, json={"notes": "arch"})
    assert r.status_code == 200, r.text
    return m.json()


def test_geometry_functions_are_exact_decimals():
    ev = lambda src: compile_expr(src).evaluate({})                       # noqa: E731
    assert str(ev("round(pi(), 10)")) == "3.1415926536"
    assert ev("sin(rad(30))") == D("0.5") and ev("round(cos(pi()), 20)") == -1
    assert round(ev("arc_length(150, 75)"), 12) == round(ev("pi() * 75"), 12)          # a true half circle
    assert round(ev("segment_area(150, 75)"), 10) == round(ev("pi() * 75 * 75 / 2"), 10)
    assert round(ev("arc_length(150, 60)"), 6) == D("207.482840")                        # flatter arch


def test_arch_unit_survey_quote_and_work_order(platform, tenant_a, client):
    code = "ARC"
    lib, branch, pl, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    arch = _arch_model(client, platform, lib, f"{code}-")
    glass = f"{code}-GLASS6"
    opening = {"location": "صالة", "opening_width_mm": 1500, "opening_height_mm": 1200, "total_height_mm": 1800,
               "model_id": lib["model"]["id"], "color_code": "W", "glass_material_code": glass}
    sv = client.post("/api/v1/surveys", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "openings": [opening]}).json()
    # no arch model chosen and no company default
    row = client.get(f"/api/v1/surveys/{sv['id']}/pricing", headers=h).json()["openings"][0]
    assert row["error"] == "ARCH_MODEL_REQUIRED"
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"],
                                                     "settings": {**company["settings"], "default_arch_model_id": arch["id"]}})
    row = client.get(f"/api/v1/surveys/{sv['id']}/pricing", headers=h).json()["openings"][0]
    assert row["error"] is None and D(row["billed_area_m2"]) == D("2.7")

    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "survey_id": sv["id"]}).json()
    unit, arch_line = q["lines"]
    assert arch_line["parent_line_id"] == unit["id"] and arch_line["model_id"] == arch["id"]
    assert (D(arch_line["opening_width_mm"]), D(arch_line["opening_height_mm"])) == (1500, 600)
    assert D(arch_line["line_total"]) == 0 and D(arch_line["unit_price"]) == 0
    pieces = {p["key"]: D(p["length_mm"]) for p in arch_line["calc"]["pieces"]}
    assert pieces["arch_base"] == 1500 and pieces["arch_curve"] == 2081      # 2074.83 + 2 × 3 mm, rounded to the system step (0.5 mm)
    pane = arch_line["calc"]["glass"][0]
    assert pane["shaped"] and D(pane["area_m2"]) < D(pane["width_mm"]) * D(pane["height_mm"]) / 1_000_000
    # the unit's cost includes the arch; the price uses width × total height
    arch_cost = D(arch_line["cost_breakdown"]["total"])
    assert arch_cost > 0 and D(unit["unit_cost"]) > arch_cost
    assert any(l.get("part") == "arch" for l in unit["cost_breakdown"]["lines"])
    assert D(unit["billed_area_m2"]) == D("2.7")
    assert D(q["subtotal"]) == D(unit["line_total"])

    # the arch line follows its unit
    r = client.patch(f"/api/v1/quotation-lines/{arch_line['id']}", headers=h, json={"version": arch_line["version"], "qty": 3})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ARCH_LINE_MANAGED"
    assert client.delete(f"/api/v1/quotation-lines/{arch_line['id']}", headers=h).status_code == 409
    q = client.patch(f"/api/v1/quotation-lines/{unit['id']}", headers=h, json={"version": unit["version"], "qty": 2}).json()
    assert [l["qty"] for l in q["lines"]] == [2, 2]
    html = client.get(f"/api/v1/quotations/{q['id']}/print", headers=h).text
    assert "أرج نصف دائري" in html and html.count("<td class=\"num\"><b>ARCH") == 0

    # work order: the arch is a unit to make (own frame)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    assert [i["model_id"] for i in wo["items"]] == [lib["model"]["id"], arch["id"]]
    mfg = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h)
    assert mfg.status_code == 200, mfg.text

    # no total height above the opening -> no arch line
    q2 = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{**{k: v for k, v in opening.items()}, "total_height_mm": 1800}]}).json()
    line = q2["lines"][0]
    q2 = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=h,
                      json={"version": line["version"], "total_height_mm": None}).json()
    assert len(q2["lines"]) == 1 and q2["lines"][0]["parent_line_id"] is None
    q2 = client.delete(f"/api/v1/quotation-lines/{q2['lines'][0]['id']}", headers=h).json()
    assert q2["lines"] == []
