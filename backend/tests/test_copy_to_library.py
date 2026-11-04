"""MYTech developer copies a company's own systems into the platform library."""
from tests.library_helpers import build_library


def _sources(client, actor):
    r = client.get("/api/v1/library/copy/sources", headers=actor.h)
    assert r.status_code == 200, r.text
    return r.json()


def test_copy_company_system_into_library(platform, tenant_a, client):
    # a system entered under the customer company (not the library)
    lib = build_library(client, tenant_a, code="COPY-SRC", prefix="CS-", publish=False, color_codes=("CSW", "CSB"))
    assert lib["system"]["company_id"] == str(tenant_a.id)

    # the developer sees the company and its systems as a copy source
    sources = _sources(client, platform)
    company = next(c for c in sources if c["company_id"] == str(tenant_a.id))
    entry = next(s for s in company["systems"] if s["code"] == "COPY-SRC")
    assert entry["already_in_library"] is False and entry["models_count"] == 1

    # copy it into the library
    r = client.post("/api/v1/library/copy/run", headers=platform.h,
                    json={"company_id": str(tenant_a.id), "system_ids": [lib["system"]["id"]]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [c["code"] for c in out["copied"]] == ["COPY-SRC"] and out["skipped"] == []

    # a fresh, unpublished library system with the same code now exists, owned by the platform
    systems = client.get("/api/v1/library/systems", headers=platform.h, params={"include_inactive": True}).json()
    copied = next(s for s in systems if s["code"] == "COPY-SRC")
    assert copied["is_library"] is True
    assert copied["id"] != lib["system"]["id"]           # a new row, not the company's
    assert copied["current_version_id"] is None          # unpublished — the developer publishes it

    # its models, materials and a test case came across
    models = client.get("/api/v1/library/models", headers=platform.h, params={"system_id": copied["id"]}).json()
    assert len(models) == 1
    tests = client.get(f"/api/v1/library/models/{models[0]['id']}/tests", headers=platform.h).json()
    assert len(tests) == 1
    mats = client.get("/api/v1/library/materials", headers=platform.h, params={"system_id": copied["id"]}).json()
    assert {m["code"] for m in mats["items"]} >= {"CS-FRAME", "CS-SASH"}

    # the developer can publish the copy and export it as a package
    v = client.post(f"/api/v1/library/systems/{copied['id']}/publish", headers=platform.h, json={"notes": "v1"})
    assert v.status_code == 200, v.text

    # the company's original system is untouched (still its own, still visible to it)
    a_systems = client.get("/api/v1/library/systems", headers=tenant_a.h).json()
    assert any(s["id"] == lib["system"]["id"] for s in a_systems)


def test_copy_skips_a_code_already_in_the_library(platform, tenant_a, client):
    build_library(client, platform, code="COPY-DUP", prefix="CD-", publish=False, color_codes=("CDW",))       # already in the library
    src = build_library(client, tenant_a, code="COPY-DUP", prefix="CD2-", publish=False, color_codes=("CDW",))  # same code under a company
    r = client.post("/api/v1/library/copy/run", headers=platform.h,
                    json={"company_id": str(tenant_a.id), "system_ids": [src["system"]["id"]]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["copied"] == []
    assert out["skipped"] == [{"code": "COPY-DUP", "name": src["system"]["name"], "reason": "code_exists"}]


def test_only_platform_can_copy(tenant_a, tenant_b, client):
    lib = build_library(client, tenant_a, code="COPY-NOPE", prefix="CN-", publish=False, color_codes=("CNW",))
    for actor in (tenant_a, tenant_b):
        r = client.get("/api/v1/library/copy/sources", headers=actor.h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "PLATFORM_ONLY"
        r = client.post("/api/v1/library/copy/run", headers=actor.h,
                        json={"company_id": str(tenant_a.id), "system_ids": [lib["system"]["id"]]})
        assert r.status_code == 403 and r.json()["error"]["code"] == "PLATFORM_ONLY"
