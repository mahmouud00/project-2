"""A model's code can be changed: unique in its system, and published versions still find the model."""
from tests.library_helpers import build_library


def test_change_model_code(platform, tenant_a, client):
    lib = build_library(client, platform, code="MCODE")
    h, model = platform.h, lib["model"]
    other = client.post("/api/v1/library/models", headers=h, json={
        "system_id": lib["system"]["id"], "code": "OTHER", "name": "تاني", "definition": {}}).json()
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=h, json={"version": model["version"], "code": "OTHER"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_CODE"
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=h, json={"version": model["version"], "code": " W05KP "})
    assert r.status_code == 200 and r.json()["code"] == "W05KP", r.text
    # the published version still has the old code: the calculation finds the model by its id
    calc = client.post("/api/v1/engine/calculate", headers=tenant_a.h, json={
        "model_id": model["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "params": {"leaf_count": 2}})
    assert calc.status_code == 200 and calc.json()["ok"], calc.text
    # a later model taking the old code does not steal the old version's calculation
    r = client.patch(f"/api/v1/library/models/{other['id']}", headers=h, json={"version": other["version"], "code": "SL2"})
    assert r.status_code == 200
    calc = client.post("/api/v1/engine/calculate", headers=tenant_a.h, json={
        "model_id": model["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "params": {"leaf_count": 2}})
    assert calc.status_code == 200 and calc.json()["pieces"], calc.text
    assert client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=h, json={"notes": "v2"}).status_code == 200
