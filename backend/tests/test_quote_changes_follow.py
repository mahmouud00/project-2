"""A quotation changed after its work order was made: the order follows (windows, total, cut sheet) at any stage
before delivery; during manufacturing the old cut sheet is kept and production is told; a new total sends the sale
back to the accounts; a delivered order's quotation is locked."""
from decimal import Decimal as D

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from tests.test_installation_order import _made, _to


def _wo(client, h, wo):
    return client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()


def _saved(tenant, wo_id):
    from app.db.session import tenant_session
    from app.modules.production.models import WorkOrder
    db = tenant_session(tenant.id)
    try:
        w = db.get(WorkOrder, wo_id)
        return w.outputs, w.outputs_history
    finally:
        db.close()


def test_order_follows_its_quotation(platform, tenant_a, client):
    code = "QCH"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _accepted_order(client, h, lib, branch, customer, code)        # 1000 x 1000, 2 windows
    q = client.get(f"/api/v1/quotations/{wo['quotation_id']}", headers=h).json()
    assert q["status"] == "accepted" and q["work_order_id"] == wo["id"]
    client.post(f"/api/v1/work-orders/{wo['id']}/manufacturing/generate", headers=h)

    # before manufacturing: a size changes, the order and its cut sheet follow
    line = q["lines"][0]
    r = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=h,
                     json={"version": line["version"], "opening_width_mm": 1500})
    assert r.status_code == 200, r.text
    w = _wo(client, h, wo)
    assert all(D(i["opening_width_mm"]) == 1500 for i in w["items"])
    assert D(w["total"]) == D(r.json()["total"])
    outputs, _ = _saved(tenant_a, wo["id"])
    assert all(D(d["opening_width_mm"]) == 1500 for d in outputs["drawings"])

    # made (sale confirmed, now in quality): a change keeps the old cut sheet and tells production
    w = _made(client, h, _wo(client, h, wo), branch, customer, code)
    assert w["sale_status"] == "approved"
    q = client.get(f"/api/v1/quotations/{wo['quotation_id']}", headers=h).json()
    line = q["lines"][0]
    old_cut = _saved(tenant_a, wo["id"])[0]["cut_list"]
    r = client.patch(f"/api/v1/quotation-lines/{line['id']}", headers=h,
                     json={"version": line["version"], "opening_height_mm": 1300, "manual_unit_price": "9000"})
    assert r.status_code == 200, r.text
    w = _wo(client, h, wo)
    assert all(D(i["opening_height_mm"]) == 1300 for i in w["items"])
    outputs, history = _saved(tenant_a, wo["id"])
    assert outputs["cut_list"] != old_cut and history[0]["outputs"]["cut_list"] == old_cut
    assert w["sale_status"] == "pending"                          # the total changed: the accounts confirm again
    inbox = client.get("/api/v1/notifications", headers=h).json()["items"]
    assert any("اتعدل" in n["title"] for n in inbox)

    # delivered: the quotation is locked
    w = _to(client, h, w, "delivered")
    q = client.get(f"/api/v1/quotations/{wo['quotation_id']}", headers=h).json()
    assert q["work_order_id"] is None
    r = client.patch(f"/api/v1/quotation-lines/{q['lines'][0]['id']}", headers=h,
                     json={"version": q["lines"][0]["version"], "opening_width_mm": 900})
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUOTE_LOCKED"
