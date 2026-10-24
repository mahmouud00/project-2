"""Builds a small sample library through the public API (test data only)."""
from __future__ import annotations

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")

DEFINITION = {
    "params": [{"name": "leaf_count", "label": "عدد الضلف", "type": "int", "default": 2, "min": 2, "max": 4}],
    "formulas": [
        {"key": "frame_w", "label": "حلق عرض", "expr": "width + 2 * weld_allowance"},
        {"key": "frame_h", "label": "حلق ارتفاع", "expr": "height + 2 * weld_allowance"},
        {"key": "sash_w", "label": "عرض الضلفة", "expr": "(width + sash_overlap_total) / leaf_count"},
        {"key": "sash_h", "label": "ارتفاع الضلفة", "expr": "height - sash_height_deduction"},
    ],
    "pieces": [
        {"key": "frame_top", "label": "حلق أفقي", "role": "frame", "material_code": "T-FRAME",
         "length_expr": "frame_w", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
        {"key": "frame_side", "label": "حلق رأسي", "role": "frame", "material_code": "T-FRAME",
         "length_expr": "frame_h", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
        {"key": "sash_top", "label": "ضلفة أفقي", "role": "sash", "material_code": "T-SASH",
         "length_expr": "sash_w + 2 * weld_allowance", "qty_expr": "2 * leaf_count", "angle_left": "45",
         "angle_right": "45"},
        {"key": "sash_side", "label": "ضلفة رأسي", "role": "sash", "material_code": "T-SASH",
         "length_expr": "sash_h + 2 * weld_allowance", "qty_expr": "2 * leaf_count", "angle_left": "45",
         "angle_right": "45"},
    ],
    "glass": [{"key": "pane", "label": "زجاج الضلفة", "width_expr": "sash_w - glass_deduction",
               "height_expr": "sash_h - glass_deduction", "qty_expr": "leaf_count"}],
    "accessories": [{"key": "handle", "material_code": "T-HANDLE", "qty_expr": "leaf_count"},
                    {"key": "wheels", "material_code": "T-WHEEL", "qty_expr": "2 * leaf_count",
                     "condition": "sash_w > 40"}],
    "validations": [{"expr": "width <= 400", "level": "warning", "code": "TOO_WIDE", "message": "عرض كبير"}],
    "drawing": [{"type": "frame", "w": "width", "h": "height"},
                {"type": "sash", "opening": "sliding_left", "w": "sash_w", "h": "sash_h"}],
}


def build_library(client, author, code="T-SLIDE", material_type="upvc", publish=True, prefix=None) -> dict:
    prefix = prefix or f"{code}-"
    h = author.h
    img = client.post("/api/v1/library/media", headers=h, files={"file": ("m.png", PNG, "image/png")}).json()
    system = client.post("/api/v1/library/systems", headers=h, json={
        "code": code, "name": "Test sliding", "supplier": "Test", "material_type": material_type, "unit": "cm",
        "rounding_step_mm": "0.5", "status": "approved", "image_id": img["id"]}).json()
    for name, value in (("weld_allowance", "0.3"), ("sash_overlap_total", "8.2"), ("sash_height_deduction", "7.5"),
                        ("glass_deduction", "13")):
        r = client.post(f"/api/v1/library/systems/{system['id']}/constants", headers=h,
                        json={"name": name, "label": name, "value": value, "unit": "cm"})
        assert r.status_code == 201, r.text
    for mcode, kind, unit, extra in ((f"{prefix}FRAME", "profile", "m", {"bar_length_mm": "6000", "min_piece_mm": "200"}),
                                     (f"{prefix}SASH", "profile", "m", {"bar_length_mm": "6000", "min_piece_mm": "200"}),
                                     (f"{prefix}HANDLE", "accessory", "pcs", {}), (f"{prefix}WHEEL", "accessory", "pcs", {})):
        r = client.post("/api/v1/library/materials", headers=h, json={
            "system_id": system["id"], "code": mcode, "name": mcode, "kind": kind, "unit": unit, **extra,
            "reference_cost": "100", "variants": [{"color_code": "W", "sku": mcode + "-W"},
                                                  {"color_code": "B", "sku": mcode + "-B"}]})
        assert r.status_code == 201, r.text
    definition = DEFINITION
    if prefix != "T-":
        import json
        definition = json.loads(json.dumps(DEFINITION).replace('"T-', f'"{prefix}'))
    model = client.post("/api/v1/library/models", headers=h, json={
        "system_id": system["id"], "code": "SL2", "name": "شباك جرار", "category": "window", "status": "approved",
        "image_id": img["id"], "definition": definition})
    assert model.status_code == 201, model.text
    model = model.json()
    r = client.post(f"/api/v1/library/models/{model['id']}/tests", headers=h, json={
        "name": "1000x1000 2 leaves", "opening_width_mm": "1000", "opening_height_mm": "1000",
        "params": {"leaf_count": 2},
        "expected": {"values": {"sash_w": "541", "sash_h": "925"}, "pieces": {"frame_top": "1006"},
                     "glass": {"pane": ["411", "795"]}, "accessories": {"handle": 2, "wheels": 4}}})
    assert r.status_code == 201, r.text
    version = None
    if publish:
        version = client.post(f"/api/v1/library/systems/{system['id']}/publish", headers=h, json={"notes": "v1"})
        assert version.status_code == 200, version.text
        version = version.json()
    return {"system": system, "model": model, "image": img, "version": version}
