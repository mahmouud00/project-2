from decimal import Decimal as D

import pytest

from app.engine.expr import ExprError, compile_expr


def ev(src, **env):
    return compile_expr(src).evaluate({k: D(str(v)) if not isinstance(v, bool) else v for k, v in env.items()})


@pytest.mark.parametrize("src,expected", [
    ("1 + 2 * 3", D(7)), ("(1 + 2) * 3", D(9)), ("-2 * -3", D(6)), ("10 / 4", D("2.5")), ("7 % 3", D(1)),
    ("min(3, 1, 2)", D(1)), ("max(1, 5)", D(5)), ("abs(-4)", D(4)),
    ("round(2.5)", D(3)), ("round(2.345, 2)", D("2.35")), ("ceil(18.1)", D(19)), ("floor(18.9)", D(18)),
    ("ceil_to(101, 5)", D(105)), ("floor_to(104, 5)", D(100)), ("round_to(102.5, 5)", D(105)),
    ("if(1 < 2, 10, 20)", D(10)), ("if(1 > 2 and 3 > 2, 10, 20)", D(20)), ("if(not (1 > 2), 1, 0)", D(1)),
    ("lookup(100, 110, 16, 135, 18, 25)", D(16)), ("lookup(135, 110, 16, 135, 18, 25)", D(18)),
    ("lookup_lt(135, 110, 16, 135, 18, 25)", D(25)), ("clamp(5, 0, 3)", D(3)),
])
def test_arithmetic(src, expected):
    assert ev(src) == expected


def test_names_and_arabic_identifiers():
    assert ev("عرض + سماحية_اللحام * 2", عرض=100, سماحية_اللحام=D("0.3")) == D("100.6")
    assert compile_expr("(width + overlap) / leaf_count").names == {"width", "overlap", "leaf_count"}


def test_decimal_is_exact():
    assert ev("0.1 + 0.2") == D("0.3")


@pytest.mark.parametrize("src,code", [
    ("__import__('os')", "EXPR_SYNTAX"), ("os.system", "EXPR_SYNTAX"), ("a.__class__", "EXPR_SYNTAX"),
    ("open(1)", "EXPR_UNKNOWN_FUNCTION"), ("eval(1)", "EXPR_UNKNOWN_FUNCTION"), ("1 +", "EXPR_SYNTAX"),
    ("(1", "EXPR_SYNTAX"), ("1 2", "EXPR_SYNTAX"), ("lambda: 1", "EXPR_SYNTAX"), ("[1]", "EXPR_SYNTAX"),
    ("x ** 2", "EXPR_SYNTAX"), ("if(1, 2)", "EXPR_ARGS"), ("round()", "EXPR_ARGS"),
    ("(" * 100 + "1" + ")" * 100, "EXPR_TOO_COMPLEX"), ("1+" * 1500 + "1", "EXPR_TOO_LONG"),
])
def test_rejects_unsafe_or_invalid(src, code):
    with pytest.raises(ExprError) as e:
        compile_expr(src)
    assert e.value.code == code


def test_runtime_errors():
    with pytest.raises(ExprError) as e:
        ev("1 / (2 - 2)")
    assert e.value.code == "EXPR_MATH"
    with pytest.raises(ExprError) as e:
        ev("missing + 1")
    assert e.value.code == "EXPR_UNKNOWN_NAME"


def test_if_is_lazy():
    assert ev("if(x > 0, 10 / x, 0)", x=0) == 0


def test_division_precision():
    assert abs(ev("(300 + 11.2) / 3") - D("103.733333333333333333333")) < D("1e-20")
