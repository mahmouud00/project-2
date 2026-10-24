from decimal import Decimal as D

from tests.library_helpers import PNG, build_library


def test_vendor_builds_and_customer_uses_library(platform, tenant_a, client):
    lib = build_library(client, platform)
    assert lib["version"]["version_no"] == 1
    systems = client.get("/api/v1/library/systems", headers=tenant_a.h).json()
    s = next(x for x in systems if x["id"] == lib["system"]["id"])
    assert s["is_library"] is True
    r = client.post("/api/v1/engine/calculate", headers=tenant_a.h, json={
        "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "params": {"leaf_count": 2}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ok"] and res["meta"]["version_no"] == 1
    pieces = {p["key"]: p for p in res["pieces"]}
    assert D(pieces["frame_top"]["length_mm"]) == D(1006) and pieces["sash_top"]["qty"] == 4
    assert {a["key"]: a["qty"] for a in res["accessories"]} == {"handle": "2", "wheels": "4"}
    assert D(res["glass"][0]["width_mm"]) == D(411)
    # model image downloadable by the customer (shown on quotes / work orders)
    img = client.get(lib["image"]["url"], headers=tenant_a.h)
    assert img.status_code == 200 and img.content == PNG


def test_customer_cannot_edit_library(platform, tenant_a, client):
    lib = build_library(client, platform, code="T-RO")
    r = client.patch(f"/api/v1/library/systems/{lib['system']['id']}", headers=tenant_a.h,
                     json={"version": lib["system"]["version"], "name": "hacked"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "LIBRARY_READ_ONLY"
    r = client.patch(f"/api/v1/library/models/{lib['model']['id']}", headers=tenant_a.h,
                     json={"version": lib["model"]["version"], "name": "hacked"})
    assert r.status_code == 403


def test_calibration_versioning_and_old_orders(platform, tenant_a, tenant_b, client):
    lib = build_library(client, platform, code="T-VER")
    sid, mid = lib["system"]["id"], lib["model"]["id"]
    body = {"model_id": mid, "opening_width_mm": 1000, "opening_height_mm": 1000}

    def frame_top(tenant, **extra):
        r = client.post("/api/v1/engine/calculate", headers=tenant.h, json={**body, **extra})
        assert r.status_code == 200, r.text
        return D(next(p for p in r.json()["pieces"] if p["key"] == "frame_top")["length_mm"])

    assert frame_top(tenant_a) == D(1006)
    r = client.put(f"/api/v1/library/systems/{sid}/adjustments", headers=tenant_a.h,
                   json={"calibrations": [{"constant_name": "weld_allowance", "delta": "0.1"}]})
    assert r.status_code == 200, r.text
    assert frame_top(tenant_a) == D(1008)   # +1 mm per weld side for A
    assert frame_top(tenant_b) == D(1006)   # B unaffected

    consts = client.get(f"/api/v1/library/systems/{sid}/constants", headers=platform.h).json()
    weld = next(c for c in consts if c["name"] == "weld_allowance")
    r = client.patch(f"/api/v1/library/constants/{weld['id']}", headers=platform.h,
                     json={"version": weld["version"], "value": "0.4"})
    assert r.status_code == 200
    # unpublished change does not affect customers
    assert frame_top(tenant_b) == D(1006)
    # publishing fails: the vendor's own reference test now drifts
    r = client.post(f"/api/v1/library/systems/{sid}/publish", headers=platform.h, json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PUBLISH_FAILED"
    tests = client.get(f"/api/v1/library/models/{mid}/tests", headers=platform.h).json()
    client.delete(f"/api/v1/library/tests/{tests[0]['id']}", headers=platform.h)
    v2 = client.post(f"/api/v1/library/systems/{sid}/publish", headers=platform.h, json={"notes": "weld 4mm"}).json()
    assert v2["version_no"] == 2
    assert frame_top(tenant_b) == D(1008)
    assert frame_top(tenant_a) == D(1010)   # calibration kept across the library update
    # an old order recalculated with its stored version gives the old numbers
    assert frame_top(tenant_b, version_id=lib["version"]["id"]) == D(1006)
    versions = client.get(f"/api/v1/library/systems/{sid}/versions", headers=tenant_a.h).json()
    assert [v["version_no"] for v in versions] == [2, 1]


def test_republish_without_changes_is_noop(platform, client):
    lib = build_library(client, platform, code="T-NOOP")
    again = client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=platform.h, json={}).json()
    assert again["id"] == lib["version"]["id"]


def test_invalid_definition_rejected(platform, client):
    lib = build_library(client, platform, code="T-BAD", publish=False)
    m = lib["model"]
    bad = dict(m["definition"])
    bad["formulas"] = bad["formulas"] + [{"key": "x", "expr": "y + 1"}, {"key": "y", "expr": "x + 1"}]
    r = client.patch(f"/api/v1/library/models/{m['id']}", headers=platform.h, json={"version": m["version"],
                                                                                     "definition": bad})
    assert r.status_code == 200
    assert any("Circular" in e for e in client.post(f"/api/v1/library/models/{m['id']}/check",
                                                    headers=platform.h).json()["errors"])
    r = client.post(f"/api/v1/library/systems/{lib['system']['id']}/publish", headers=platform.h, json={})
    assert r.status_code == 422
    bad["pieces"] = bad["pieces"] + [{"key": "z", "material_code": "NOPE", "length_expr": "1"}]
    r = client.patch(f"/api/v1/library/models/{m['id']}", headers=platform.h,
                     json={"version": m["version"] + 1, "definition": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_MATERIAL"
    r = client.patch(f"/api/v1/library/models/{m['id']}", headers=platform.h,
                     json={"version": m["version"] + 1, "definition": {"formulas": [{"key": "1bad", "expr": "1"}]}})
    assert r.status_code == 422


def test_preview_draft_before_publishing(platform, client):
    lib = build_library(client, platform, code="T-PREV", publish=False)
    r = client.post(f"/api/v1/library/models/{lib['model']['id']}/preview", headers=platform.h,
                    json={"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000})
    assert r.status_code == 200 and r.json()["ok"]
    run = client.post(f"/api/v1/library/models/{lib['model']['id']}/tests/run", headers=platform.h).json()
    assert run["passed"] is True


def test_company_private_system_is_isolated(tenant_a, tenant_b, client):
    lib = build_library(client, tenant_a, code="A-OWN", prefix="A-")
    assert lib["system"]["company_id"] == str(tenant_a.id)
    assert all(s["id"] != lib["system"]["id"] for s in client.get("/api/v1/library/systems", headers=tenant_b.h).json())
    r = client.post("/api/v1/engine/calculate", headers=tenant_b.h, json={
        "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000})
    assert r.status_code == 404
    assert client.get(lib["image"]["url"], headers=tenant_b.h).status_code == 404


def test_unlicensed_material_type_hidden(platform, tenant_a, client):
    from app.licensing.provider import Entitlements, set_license_provider

    lib = build_library(client, platform, code="T-ALU", material_type="aluminum", prefix="AL-")

    class UpvcOnly:
        def entitlements(self, db, company_id):
            return Entitlements("valid", {"core", "manufacturing", "mfg.upvc"})

    set_license_provider(UpvcOnly())
    assert all(s["id"] != lib["system"]["id"] for s in client.get("/api/v1/library/systems", headers=tenant_a.h).json())
    r = client.post("/api/v1/engine/calculate", headers=tenant_a.h, json={
        "model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000})
    assert r.status_code == 404


def test_upload_rejects_non_images(platform, client):
    r = client.post("/api/v1/library/media", headers=platform.h, files={"file": ("x.svg", b"<svg/>", "image/svg+xml")})
    assert r.status_code == 422


def test_sales_user_cannot_author(tenant_a, client):
    roles = {r["code"]: r for r in client.get("/api/v1/roles", headers=tenant_a.h).json()}
    client.post("/api/v1/users", headers=tenant_a.h, json={"username": "s1", "password": "user-pass-123",
                                                          "full_name": "s", "assignments": [{"role_id": roles["sales"]["id"]}]})
    h = tenant_a.headers("s1", "user-pass-123")
    r = client.post("/api/v1/library/systems", headers=h, json={"code": "X", "name": "x", "material_type": "upvc"})
    assert r.status_code == 403
