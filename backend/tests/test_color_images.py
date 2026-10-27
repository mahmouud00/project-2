"""A model can have a picture per colour; quotes, invoices and documents use the picture of the line's colour."""
from tests.library_helpers import PNG
from tests.test_business_flow import _setup, price_at_top


def test_picture_follows_the_colour(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "CLR")
    model = lib["model"]
    beige = client.post("/api/v1/library/media", headers=platform.h,
                        files={"file": ("beige.png", PNG + b"beige", "image/png")}).json()
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=platform.h,
                     json={"version": model["version"], "color_images": {"B": beige["id"]}})
    assert r.status_code == 200 and r.json()["color_images"] == {"B": beige["id"]}
    h = tenant_a.h
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
        "lines": [{"model_id": model["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "B",
                   "glass_material_code": "CLR-GLASS6"},
                  {"model_id": model["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
                   "glass_material_code": "CLR-GLASS6"}]}).json()
    assert [l["model_image_id"] for l in q["lines"]] == [beige["id"], lib["image"]["id"]]
    q = price_at_top(client, h, q)
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"], "status": "accepted"}).json()
    inv = client.post("/api/v1/invoices", headers=h, json={"quotation_id": q["id"]}).json()
    assert [l["model_image_id"] for l in inv["lines"]] == [beige["id"], lib["image"]["id"]]
    # removing the colour pictures goes back to the main picture
    m = client.get(f"/api/v1/library/models/{model['id']}", headers=platform.h).json()
    r = client.patch(f"/api/v1/library/models/{model['id']}", headers=platform.h,
                     json={"version": m["version"], "color_images": None})
    assert r.json()["color_images"] == {}


def test_colour_pictures_travel_in_library_packages(platform, client):
    import io
    import json
    import zipfile

    from tests.library_helpers import build_library

    lib = build_library(client, platform, code="CLR-PKG")
    model = lib["model"]
    beige = client.post("/api/v1/library/media", headers=platform.h,
                        files={"file": ("b.png", PNG + b"pkg-beige", "image/png")}).json()
    client.patch(f"/api/v1/library/models/{model['id']}", headers=platform.h,
                 json={"version": model["version"], "color_images": {"B": beige["id"]}})
    raw = client.post("/api/v1/library/packages/export", headers=platform.h,
                      json={"system_codes": ["CLR-PKG"], "notes": "t"}).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    payload = json.loads(z.read("package.json"))["payload"]
    assert beige["id"] in {m["id"] for m in payload["media"]}
    assert payload["systems"][0]["models"][0]["row"]["color_images"] == {"B": beige["id"]}
