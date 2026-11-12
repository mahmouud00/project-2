"""Each system says how its bars are cut: 45° allowances for frame / sash / bead pieces, the saw's thickness and
the waste at a bar's start. The cut lengths never change; the bar plan (and so what is bought) does."""
from decimal import Decimal as D

from app.engine.cutting import optimise
from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order


def test_extra_and_start_in_the_plan():
    # 3 pieces of 190 cm fit a 600 cm bar; with 5 cm more each (a 45° cut) and 20 cm lost at the start they do not
    pieces = [{"length_mm": D(1900), "qty": 3}]
    assert optimise(pieces, bar_length_mm=D(6000))["bars_count"] == 1
    pieces = [{"length_mm": D(1900), "qty": 3, "extra_mm": D(50)}]
    assert optimise(pieces, bar_length_mm=D(6000))["bars_count"] == 1          # 5850 still fits
    assert optimise(pieces, bar_length_mm=D(6000), start_mm=D(200))["bars_count"] == 2


def test_system_values_change_the_bar_plan(platform, tenant_a, client):
    code = "SCUT"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h, ph = tenant_a.h, platform.h
    wo = _accepted_order(client, h, lib, branch, customer, code)      # 2 windows: 8 frame pieces (45° both ends)
    frame = lambda: next(p for p in client.post(f"/api/v1/work-orders/{wo['id']}/manufacturing/generate",  # noqa: E731
                                                headers=h).json()["optimisation"] if p["sku"] == f"{code}-FRAME-W")
    before = frame()
    system = client.get(f"/api/v1/library/systems/{lib['system']['id']}", headers=ph).json()
    r = client.patch(f"/api/v1/library/systems/{system['id']}", headers=ph, json={
        "version": system["version"], "miter_frame_mm": "450", "saw_kerf_mm": "5", "bar_start_waste_mm": "200"})
    assert r.status_code == 200 and D(r.json()["miter_frame_mm"]) == 450, r.text
    after = frame()
    assert after["bars_count"] > before["bars_count"]
    lengths = {D(p["length_mm"]) for b in after["bars"] for p in b["pieces"]}
    assert lengths == {D(p["length_mm"]) for b in before["bars"] for p in b["pieces"]}   # the cut lengths stay


def test_role_from_the_name_when_none_was_saved():
    from app.modules.production.manufacturing import miter_extra
    cut = {"miter_frame_mm": D(40), "miter_sash_mm": D(30), "miter_bead_mm": D(20)}
    assert miter_extra({"label": "حلق عرض", "angle_left": "45", "angle_right": "45"}, cut) == 40
    assert miter_extra({"element": "ضلفة", "angle_left": "90", "angle_right": "45"}, cut) == 30
    assert miter_extra({"label": "باكتة", "angle_left": "45", "angle_right": "45", "role": None}, cut) == 20
    assert miter_extra({"label": "حلق", "angle_left": "90", "angle_right": "90"}, cut) == 0
    assert miter_extra({"label": "قاطوع", "angle_left": "45", "angle_right": "45"}, cut) == 0
    assert miter_extra({"element": "الحلق", "angle_left": "45", "angle_right": "45"}, cut) == 40
    assert miter_extra({"label": "عرض", "material_name": "حلق مفصلي بار 5 سم", "angle_left": "45", "angle_right": "45"}, cut) == 40
