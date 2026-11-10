"""«حساب طلبية الشراء»: a model's own purchase rows decide what is bought; the cut list keeps the pieces."""
from decimal import Decimal as D

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order


def _needs(client, h, wo):
    r = client.get(f"/api/v1/work-orders/{wo['id']}/material-needs", headers=h)
    assert r.status_code == 200, r.text
    return {n["sku"]: n for n in r.json()}


def test_purchase_rows_decide_the_bars(platform, tenant_a, client):
    code = "PURROW"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h, ph = tenant_a.h, platform.h
    # without purchase rows: as before, from the cut plan (1000 x 1000, qty 2: 8 frame pieces of ~1 m = 2 bars)
    before = _needs(client, h, _accepted_order(client, h, lib, branch, customer, code))
    assert before[f"{code}-FRAME-W"]["bars"] == 2

    model = client.get(f"/api/v1/library/models/{lib['model']['id']}", headers=ph).json()
    d = model["definition"]
    # each frame piece takes 155 cm of bar when buying: only 3 fit in a 6 m bar, so 8 pieces need 3 bars
    d["purchase"] = [{"key": "frame_buy", "label": "حلق للشراء", "material_code": f"{code}-FRAME",
                      "length_expr": "frame_w - frame_w + 155", "qty_expr": "4"}]
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=ph, json={"version": model["version"], "definition": d})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/library/models/{model['id']}/check", headers=ph).json()["errors"] == []
    assert client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=ph, json={"notes": "شراء"}).status_code == 200

    wo = _accepted_order(client, h, lib, branch, customer, code)
    by = _needs(client, h, wo)
    frame = by[f"{code}-FRAME-W"]
    assert frame["bars"] == 3
    assert D(frame["qty"]) == D(frame["bar_length_mm"]) * 3 / 1000
    assert by[f"{code}-SASH-W"]["bars"] == before[f"{code}-SASH-W"]["bars"]   # no rows for the sash: the cut plan
    # the cut list still has the real pieces
    cut = client.get(f"/api/v1/work-orders/{wo['id']}", headers=h).json()
    out = cut.get("outputs") or {}
    if out:
        frame_cut = next(g for g in out["cut_list"] if g["sku"] == f"{code}-FRAME-W")
        assert {p["label"] for p in frame_cut["pieces"]} >= {"حلق أفقي", "حلق رأسي"}


def test_purchase_rows_are_checked(platform, client):
    from tests.library_helpers import build_library
    lib = build_library(client, platform, code="PURCHK", publish=False)
    model = client.get(f"/api/v1/library/models/{lib['model']['id']}", headers=platform.h).json()
    d = model["definition"]
    d["purchase"] = [{"key": "x", "material_code": "PURCHK-FRAME", "length_expr": "no_such_name + 1"}]
    client.patch(f"/api/v1/library/models/{model['id']}", headers=platform.h, json={"version": model["version"], "definition": d})
    errors = client.post(f"/api/v1/library/models/{model['id']}/check", headers=platform.h).json()["errors"]
    assert any("طلبية الشراء" in str(e) and "no_such_name" in str(e) for e in errors), errors
