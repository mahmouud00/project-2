"""The glass order: by glass type with each type's m²; with no glass type chosen, by the glass as written on the
survey (colour and single / double), carried to the quotation and the work order."""
from tests.test_business_flow import _setup, price_at_top


def test_glass_as_written_on_the_survey(platform, tenant_a, client):
    code = "GLW"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    model_id = lib["model"]["id"]
    survey = client.post("/api/v1/surveys", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "openings": [
            {"location": "صالة", "opening_width_mm": 1000, "opening_height_mm": 1000, "model_id": model_id,
             "color_code": "W", "glass_color": "عاكس بني", "glass_layers": "single"},
            {"location": "مطبخ", "opening_width_mm": 800, "opening_height_mm": 800, "model_id": model_id,
             "color_code": "W", "glass_material_code": f"{code}-GLASS6"}]}).json()
    q = client.post("/api/v1/quotations", headers=h, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "survey_id": survey["id"]}).json()
    assert [l["glass_text"] for l in q["lines"]] == ["عاكس بني - سنجل", None]
    # written by hand on a line too
    line = q["lines"][1]
    r = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=h, json={"version": line["version"], "notes": "x"})
    assert r.status_code == 200, r.text
    q = price_at_top(client, h, r.json())
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    assert sorted(i["glass_text"] or "" for i in wo["items"]) == ["", "عاكس بني - سنجل"]
    html = client.get(f"/api/v1/work-orders/{wo['id']}/print/glass", headers=h).text
    assert "عاكس بني - سنجل" in html and "إجمالي الأمتار لكل نوع زجاج" in html
    # an order made before the glass was kept: taken from the survey; and set on the order by hand
    from app.db.session import tenant_session
    from app.modules.production.models import WorkOrderItem
    from sqlalchemy import update
    db = tenant_session(tenant_a.id)
    db.execute(update(WorkOrderItem).where(WorkOrderItem.work_order_id == wo["id"]).values(glass_text=None))
    db.commit()
    db.close()
    assert "عاكس بني - سنجل" in client.get(f"/api/v1/work-orders/{wo['id']}/print/glass", headers=h).text
    r = client.put(f"/api/v1/work-orders/{wo['id']}/glass", headers=h, json={"glass_text": "شفاف - دبل"})
    assert r.status_code == 200, r.text
    html = client.get(f"/api/v1/work-orders/{wo['id']}/print/glass", headers=h).text
    assert "شفاف - دبل" in html and "عاكس بني" not in html


def test_glass_type_from_the_model(platform, tenant_a, client):
    """A glass type chosen from the model's own list (not a material) goes to the glass order by its name."""
    code = "GLT"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h, ph = tenant_a.h, platform.h
    model = client.get(f"/api/v1/library/models/{lib['model']['id']}", headers=ph).json()
    d = model["definition"]
    d["glass_types"] = [{"key": "شفاف", "name": "شفاف 6 مم"}, {"key": "عاكس_بني", "name": "عاكس بني سنجل"}]
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=ph, json={"version": model["version"], "definition": d})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/library/models/{model['id']}/check", headers=ph).json()["errors"] == []
    assert client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=ph, json={"notes": "زجاج"}).status_code == 200
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"], "lines": [
        {"model_id": model["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
         "params": {"نوع_الزجاج": 2}, "location": "صالة"}]})
    assert q.status_code == 201, q.text
    q = price_at_top(client, h, q.json())
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    html = client.get(f"/api/v1/work-orders/{wo['id']}/print/glass", headers=h).text
    assert "عاكس بني سنجل" in html
