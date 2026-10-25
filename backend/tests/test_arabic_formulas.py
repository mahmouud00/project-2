"""Formulas written in Arabic give exactly the same results as the English spelling."""
from decimal import Decimal as D

import pytest

from app.engine.compute import calculate, check_definition
from app.engine.expr import ExprError, compile_expr
from tests.test_engine_compute import snap


def ev(src, **env):
    return compile_expr(src).evaluate({k: D(str(v)) for k, v in env.items()})


@pytest.mark.parametrize("arabic,english", [
    ("العرض + ٢ × سماحية_اللحام", "width + 2 * سماحية_اللحام"),
    ("(العرض + ٨٫٢) ÷ عدد_الضلف", "(width + 8.2) / عدد_الضلف"),
    ("لو(العرض > ١٠٠ و الارتفاع < ٢٠٠، ١، ٢)", "if(width > 100 and height < 200, 1, 2)"),
    ("أكبر(العرض، الارتفاع) - أصغر(العرض، الارتفاع)", "max(width, height) - min(width, height)"),
    ("تقريب_لخطوة(العرض ÷ ٣، ٠٫٥)", "round_to(width / 3, 0.5)"),
    ("جدول(الارتفاع، ١٣٥، ١٨، ١٩٠، ٢٠، ٠)", "lookup(height, 135, 18, 190, 20, 0)"),
    ("طول_القوس(العرض، الارتفاع - ١٠٠)", "arc_length(width, height - 100)"),
    ("مش (العرض > ٣٠٠) أو خطأ", "not (width > 300) or false"),
])
def test_arabic_equals_english(arabic, english):
    env = {"width": 150, "height": 180, "سماحية_اللحام": "0.3", "عدد_الضلف": 2}
    assert ev(arabic, **env) == ev(english, **env)


def test_arabic_names_resolve_to_the_built_in_sizes():
    e = compile_expr("عرض_الفتحة - خلوص_العرض + الارتفاع")
    assert e.names == {"opening_width", "install_clearance_width", "height"}
    with pytest.raises(ExprError):
        compile_expr("كذا(١)")                       # unknown function, Arabic or not


def test_whole_model_in_arabic():
    s = snap()
    s["constants"]["سماحية_اللحام"] = {"value": "3"}
    s["model"]["params"] = [{"name": "عدد_المقابض", "type": "int", "default": 1, "min": 0, "max": 4}]
    s["model"]["formulas"] = [{"key": "حلق_عرض", "expr": "العرض + ٢ × سماحية_اللحام", "unit": "length"},
                              {"key": "حلق_ارتفاع", "expr": "الارتفاع + ٢ × سماحية_اللحام", "unit": "length"}]
    s["model"]["pieces"][0]["length_expr"] = "حلق_عرض"
    s["model"]["pieces"][1]["length_expr"] = "حلق_ارتفاع"
    s["model"]["accessories"][0].update(qty_expr="عدد_المقابض", condition="الارتفاع > ٥٠٠")
    assert check_definition(s) == []
    arabic = calculate(s, opening_width_mm=1000, opening_height_mm=1200)
    english = calculate(snap(), opening_width_mm=1000, opening_height_mm=1200)
    assert [p["length_mm"] for p in arabic.pieces] == [p["length_mm"] for p in english.pieces]
    assert arabic.accessories[0]["qty"] == english.accessories[0]["qty"]


def test_arabic_built_in_names_are_reserved():
    s = snap()
    s["model"]["params"] = [{"name": "العرض", "type": "int", "default": 1}]
    assert any("reserved" in e for e in check_definition(s))
