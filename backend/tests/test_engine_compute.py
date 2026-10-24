import copy
from decimal import Decimal as D

import pytest

from app.engine.compute import CalcError, calculate, check_definition


def snap(**over):
    s = {
        "system": {"code": "S", "name": "S", "material_type": "upvc", "unit": "mm", "rounding_step_mm": "0.5",
                   "rounding_mode": "half_up"},
        "constants": {"install_clearance_width": {"value": "10"}, "install_clearance_height": {"value": "10"},
                      "weld_allowance": {"value": "3"}, "glass_clearance": {"value": "5"}},
        "materials": {"FR": {"name": "Frame", "unit": "m", "bar_length_mm": "6000", "min_piece_mm": "300"},
                      "HND": {"name": "Handle", "unit": "pcs"}},
        "model": {
            "code": "M", "name": "Fixed", "category": "window",
            "params": [{"name": "handles", "type": "int", "default": 1, "min": 0, "max": 4}],
            "formulas": [{"key": "frame_w", "expr": "width + 2 * weld_allowance", "unit": "length"},
                         {"key": "frame_h", "expr": "height + 2 * weld_allowance", "unit": "length"}],
            "pieces": [{"key": "top", "label": "حلق عرض", "role": "frame", "material_code": "FR",
                        "length_expr": "frame_w", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
                       {"key": "side", "label": "حلق ارتفاع", "role": "frame", "material_code": "FR",
                        "length_expr": "frame_h", "qty_expr": "2", "angle_left": "45", "angle_right": "45"}],
            "glass": [{"key": "g", "width_expr": "width - 2 * glass_clearance - 100",
                       "height_expr": "height - 2 * glass_clearance - 100", "qty_expr": "1"}],
            "accessories": [{"key": "h", "material_code": "HND", "qty_expr": "handles", "condition": "height > 500"}],
            "validations": [{"expr": "width <= 3000", "level": "warning", "code": "WIDE", "message": "wide"}],
            "drawing": [{"type": "frame", "x": "0", "y": "0", "w": "width", "h": "height"}],
        },
    }
    for k, v in over.items():
        s[k] = v
    return s


def test_opening_vs_manufacturing_size_and_pieces():
    r = calculate(snap(), opening_width_mm=1000, opening_height_mm=1200)
    assert r.ok
    assert r.inputs["width_mm"] == D(990) and r.inputs["opening_width_mm"] == D(1000)
    top = next(p for p in r.pieces if p["key"] == "top")
    assert top["length_mm"] == D(996) and top["qty"] == 2 and top["angle_left"] == D(45)
    assert r.glass[0]["width_mm"] == D(880)
    assert r.accessories[0]["qty"] == D(1)
    assert r.drawing[0]["w_mm"] == D(990)


def test_calibration_and_override_do_not_touch_definition():
    s = snap()
    original = copy.deepcopy(s)
    r = calculate(s, opening_width_mm=1000, opening_height_mm=1200, calibration={"weld_allowance": "1"})
    assert next(p for p in r.pieces if p["key"] == "top")["length_mm"] == D(998)
    r = calculate(s, opening_width_mm=1000, opening_height_mm=1200, overrides={"weld_allowance": "0"},
                  calibration={"weld_allowance": "0.5"})
    assert next(p for p in r.pieces if p["key"] == "top")["length_mm"] == D(991)
    assert s == original
    with pytest.raises(CalcError):
        calculate(s, opening_width_mm=1000, opening_height_mm=1200, calibration={"nope": 1})


def test_cm_systems_and_rounding():
    s = snap(system={"unit": "cm", "rounding_step_mm": "1", "rounding_mode": "down"})
    s["constants"] = {"install_clearance_width": {"value": "1"}, "install_clearance_height": {"value": "1"},
                      "weld_allowance": {"value": "0.33"}, "glass_clearance": {"value": "0.5"}}
    s["model"]["glass"][0]["width_expr"] = "width - 10"
    s["model"]["glass"][0]["height_expr"] = "height - 10"
    r = calculate(s, opening_width_mm=1000, opening_height_mm=1200)
    top = next(p for p in r.pieces if p["key"] == "top")
    assert top["length_exact_mm"] == D("996.6") and top["length_mm"] == D(996)


def test_impossible_values_are_flagged():
    r = calculate(snap(), opening_width_mm=100, opening_height_mm=1200)
    codes = {i.code for i in r.issues}
    assert "PIECE_TOO_SHORT" in codes and "GLASS_NOT_POSITIVE" in codes and not r.ok
    r = calculate(snap(), opening_width_mm=7000, opening_height_mm=1200)
    codes = {i.code for i in r.issues}
    assert "PIECE_LONGER_THAN_BAR" in codes and "WIDE" in codes


def test_params_validated():
    with pytest.raises(CalcError) as e:
        calculate(snap(), opening_width_mm=1000, opening_height_mm=1000, params={"handles": 9})
    assert e.value.code == "PARAM_RANGE"
    with pytest.raises(CalcError) as e:
        calculate(snap(), opening_width_mm=1000, opening_height_mm=1000, params={"oops": 1})
    assert e.value.code == "PARAM_UNKNOWN"


def test_definition_checks():
    s = snap()
    assert check_definition(s) == []
    s["model"]["formulas"].append({"key": "a", "expr": "b + 1"})
    s["model"]["formulas"].append({"key": "b", "expr": "a + 1"})
    s["model"]["pieces"][0]["material_code"] = "NOPE"
    s["model"]["glass"][0]["width_expr"] = "missing_name"
    del s["constants"]["install_clearance_width"]
    errors = "\n".join(check_definition(s))
    assert "Circular" in errors and "NOPE" in errors and "missing_name" in errors and "install_clearance_width" in errors


def test_element_and_side_pass_through():
    s = snap()
    s["model"]["pieces"][0].update(element="حلق", side="width")
    s["model"]["pieces"][1].update(element="حلق", side="height")
    r = calculate(s, opening_width_mm=1000, opening_height_mm=1200)
    sides = {p["key"]: (p["element"], p["side"]) for p in r.pieces}
    assert sides == {"top": ("حلق", "width"), "side": ("حلق", "height")}
