"""Every window of a work order has its own number: the cutter marks each piece «عرض 1»، «عرض 2»."""
from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from app.modules.production.manufacturing import unit_ranges


def test_unit_ranges():
    assert unit_ranges([1, 1, 2, 3, 5]) == "1–3، 5" and unit_ranges([4]) == "4" and unit_ranges([]) == ""


def test_each_window_is_numbered_in_the_cut_list_and_the_bars(platform, tenant_a, client):
    code = "WNUM"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h = tenant_a.h
    wo = _accepted_order(client, h, lib, branch, customer, code)          # one line, 2 windows
    out = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h).json()
    assert out["drawings"][0]["units"] == [1, 2]
    frame = next(g for g in out["cut_list"] if g["sku"] == f"{code}-FRAME-W")
    top = next(p for p in frame["pieces"] if p["label"] == "حلق أفقي")
    assert top["qty"] == 4 and top["units"] == [1, 1, 2, 2] and top["windows"] == "1–2"
    plan = next(p for p in out["optimisation"] if p["sku"] == f"{code}-FRAME-W")
    marks = sorted((p["label"], p["unit"]) for b in plan["bars"] for p in b["pieces"])
    assert marks.count(("حلق أفقي", 1)) == 2 and marks.count(("حلق أفقي", 2)) == 2
