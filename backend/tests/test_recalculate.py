"""A model changed and published after the quotation: the order is calculated again only when asked, before
manufacturing."""
from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order


def test_recalculate_with_the_latest_published_formulas(platform, tenant_a, client):
    code = "RECALC"
    lib, branch, _, customer = _setup(client, platform, tenant_a, code)
    h, ph = tenant_a.h, platform.h
    wo = _accepted_order(client, h, lib, branch, customer, code)
    def keys():
        out = client.get(f"/api/v1/work-orders/{wo['id']}/manufacturing", headers=h).json()
        return {p["label"] for g in out["cut_list"] for p in g["pieces"]}
    assert "حلق رأسي" in keys()

    model = client.get(f"/api/v1/library/models/{lib['model']['id']}", headers=ph).json()
    d = model["definition"]
    d["pieces"] = [p for p in d["pieces"] if p["key"] != "frame_side"]
    client.patch(f"/api/v1/library/models/{model['id']}", headers=ph, json={"version": model["version"], "definition": d})
    for t in client.get(f"/api/v1/library/models/{model['id']}/tests", headers=ph).json():     # its old reference test
        client.delete(f"/api/v1/library/models/{model['id']}/tests/{t['id']}", headers=ph)
    r = client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=ph, json={"notes": "v2"})
    assert r.status_code == 200, r.text
    assert "حلق رأسي" in keys()                     # the order does not change by itself

    r = client.post(f"/api/v1/work-orders/{wo['id']}/recalculate", headers=h)
    assert r.status_code == 200, r.text
    assert "حلق رأسي" not in keys()
