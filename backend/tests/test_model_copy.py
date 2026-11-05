"""نسخ النماذج من قطاع لقطاع: copied whole, or only what the other system's model lacks."""
from tests.library_helpers import PNG, build_library


def _copy(client, h, src, to, ids, apply):
    return client.post(f"/api/v1/library/systems/{src}/models/copy", headers=h, params={"apply": apply},
                       json={"to_system_id": to, "model_ids": ids})


def test_copy_new_and_merge_by_name(tenant_a, client):
    h = tenant_a.h
    lib = build_library(client, tenant_a, code="MC-A", publish=False)
    src, model = lib["system"], lib["model"]
    red = client.post("/api/v1/library/media", headers=h, files={"file": ("r.png", PNG, "image/png")}).json()
    client.patch(f"/api/v1/library/models/{model['id']}", headers=h,
                 json={"version": model["version"], "color_images": {"W": red["id"]}, "description": "وصف"})
    target = client.post("/api/v1/library/systems", headers=h, json={"code": "MC-B", "name": "b", "material_type": "upvc"}).json()
    client.post(f"/api/v1/library/systems/{target['id']}/constants", headers=h,
                json={"name": "weld_allowance", "label": "w", "value": "0.3", "unit": "cm"})

    # a new model in the other system: everything, as a trial; preview saves nothing
    pre = _copy(client, h, src["id"], target["id"], [model["id"]], False)
    assert pre.status_code == 200, pre.text
    row = pre.json()["models"][0]
    assert row["action"] == "new" and row["added"]["pieces"] == 4 and row["tests"] == 1
    assert set(row["constants_missing"]) == {"sash_overlap_total", "sash_height_deduction", "glass_deduction"}
    assert client.get("/api/v1/library/models", headers=h, params={"system_id": target["id"]}).json() == []
    assert _copy(client, h, src["id"], target["id"], [model["id"]], True).status_code == 200
    copied = client.get("/api/v1/library/models", headers=h, params={"system_id": target["id"], "include_inactive": True}).json()
    assert len(copied) == 1 and copied[0]["status"] == "trial" and copied[0]["definition"] == model["definition"]
    assert copied[0]["image_id"] == model["image_id"] and copied[0]["color_images"] == {"W": red["id"]}
    assert len(client.get(f"/api/v1/library/models/{copied[0]['id']}/tests", headers=h).json()) == 1
    # the same again: nothing new
    assert _copy(client, h, src["id"], target["id"], [model["id"]], False).json()["models"][0]["action"] == "same"

    # a model imported with its name only (spelled a little differently) gets the rest, keeping its own
    third = client.post("/api/v1/library/systems", headers=h, json={"code": "MC-C", "name": "c", "material_type": "upvc"}).json()
    shell = client.post("/api/v1/library/models", headers=h, json={
        "system_id": third["id"], "code": "X9", "name": "  شباك   جرار ", "category": "window",
        "definition": {"pieces": [{"key": "frame_top", "material_code": "MC-A-FRAME", "length_expr": "width"}],
                       "drawing": [{"type": "frame", "w": "width", "h": "height"}]}}).json()
    out = _copy(client, h, src["id"], third["id"], [model["id"]], True).json()["models"][0]
    assert out["action"] == "merge" and out["into_code"] == "X9"
    assert out["added"]["pieces"] == 3 and "drawing" not in out["added"] and out["tests"] == 0 and out["tests_skipped"] == 1
    merged = client.get(f"/api/v1/library/models/{shell['id']}", headers=h).json()
    pieces = {p["key"]: p for p in merged["definition"]["pieces"]}
    assert pieces["frame_top"]["length_expr"] == "width"                 # its own piece was kept as it was
    assert len(pieces) == 4 and len(merged["definition"]["formulas"]) == 4 and merged["code"] == "X9"
    assert merged["definition"]["drawing"] == [{"type": "frame", "x": "0", "y": "0", "w": "width", "h": "height"}] \
        or len(merged["definition"]["drawing"]) == 1
    assert merged["description"] == "وصف" and merged["color_images"] == {"W": red["id"]}


def test_copy_refuses_other_units_and_library_targets(platform, tenant_a, client):
    h = tenant_a.h
    lib = build_library(client, tenant_a, code="MC-D", publish=False)
    mm = client.post("/api/v1/library/systems", headers=h, json={"code": "MC-E", "name": "e", "material_type": "upvc",
                                                                  "unit": "mm"}).json()
    r = _copy(client, h, lib["system"]["id"], mm["id"], [lib["model"]["id"]], True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNIT_MISMATCH"
    mylib = build_library(client, platform, code="MC-LIB", publish=True)
    r = _copy(client, h, lib["system"]["id"], mylib["system"]["id"], [lib["model"]["id"]], True)
    assert r.status_code == 403
    # copying FROM a library system into the company's own is fine
    own = client.post("/api/v1/library/systems", headers=h, json={"code": "MC-F", "name": "f", "material_type": "upvc"}).json()
    r = _copy(client, h, mylib["system"]["id"], own["id"], [mylib["model"]["id"]], True)
    assert r.status_code == 200 and r.json()["new"] == 1, r.text


def test_missing_constants_copied_only_when_asked(tenant_a, client):
    h = tenant_a.h
    lib = build_library(client, tenant_a, code="MC-G", publish=False)
    target = client.post("/api/v1/library/systems", headers=h, json={"code": "MC-H", "name": "h", "material_type": "upvc"}).json()
    consts = lambda: {c["name"]: c["value"] for c in client.get(f"/api/v1/library/systems/{target['id']}/constants", headers=h).json()}  # noqa: E731
    r = client.post(f"/api/v1/library/systems/{lib['system']['id']}/models/copy", headers=h, params={"apply": True},
                    json={"to_system_id": target["id"], "model_ids": [lib["model"]["id"]], "copy_constants": True})
    assert r.status_code == 200 and len(r.json()["constants_copied"]) == 4, r.text
    assert {k: float(v) for k, v in consts().items()}.items() >= {"weld_allowance": 0.3, "sash_overlap_total": 8.2,
                                                          "sash_height_deduction": 7.5, "glass_deduction": 13}.items()
