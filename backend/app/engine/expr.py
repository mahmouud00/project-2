"""Safe expression language for deductions and quantities.

No eval/exec: text -> tokens -> AST (tuples) -> evaluation over Decimal.

Grammar (lowest to highest precedence):
    expr     := or
    or       := and ("or" and)*
    and      := not ("and" not)*
    not      := "not" not | cmp
    cmp      := sum (("<"|"<="|">"|">="|"=="|"!=") sum)?
    sum      := term (("+"|"-") term)*
    term     := unary (("*"|"/"|"%") unary)*
    unary    := ("-"|"+") unary | atom
    atom     := NUMBER | NAME | NAME "(" args ")" | "(" expr ")" | "true" | "false"

Names are identifiers (Latin or Arabic letters, digits, underscore; not
starting with a digit). Only whitelisted functions can be called.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation, localcontext

MAX_LENGTH = 2000
MAX_DEPTH = 60
MAX_NODES = 2000


class ExprError(Exception):
    def __init__(self, message: str, *, code: str = "EXPR_ERROR", position: int | None = None):
        super().__init__(message)
        self.code = code
        self.position = position


_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?|\.\d+)
  | (?P<name>[^\W\d]\w*)
  | (?P<op><=|>=|==|!=|[-+*/%()<>,])
""", re.VERBOSE | re.UNICODE)

KEYWORDS = {"and", "or", "not", "true", "false"}


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    if not isinstance(text, str):
        raise ExprError("Expression must be text")
    if len(text) > MAX_LENGTH:
        raise ExprError("Expression too long", code="EXPR_TOO_LONG")
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ExprError(f"Unexpected character {text[pos]!r}", code="EXPR_SYNTAX", position=pos)
        kind = m.lastgroup
        if kind != "ws":
            value = m.group(kind)
            if kind == "name" and value in KEYWORDS:
                kind = "kw"
            tokens.append(Token(kind, value, pos))
        pos = m.end()
    tokens.append(Token("end", "", len(text)))
    return tokens


# ---------------------------------------------------------------- functions
def _q(x: Decimal, step: Decimal, rounding) -> Decimal:
    if step <= 0:
        raise ExprError("Step must be positive", code="EXPR_DOMAIN")
    return (x / step).to_integral_value(rounding=rounding) * step


def _round(x, places=Decimal(0)):
    return x.quantize(Decimal(1).scaleb(-int(places)), rounding=ROUND_HALF_UP)


def _lookup(inclusive: bool):
    def fn(x, *pairs):
        """lookup(x, t1, v1, t2, v2, ..., default): first threshold that x is under."""
        if len(pairs) < 3 or len(pairs) % 2 == 0:
            raise ExprError("lookup needs threshold/value pairs and a default", code="EXPR_ARGS")
        for i in range(0, len(pairs) - 1, 2):
            if (x <= pairs[i]) if inclusive else (x < pairs[i]):
                return pairs[i + 1]
        return pairs[-1]
    return fn


# ---- geometry (arches): Decimal only, series evaluated with extra digits, no float anywhere
_PI = Decimal("3.14159265358979323846264338327950288419716939937510")


def _domain(ok: bool, message: str) -> None:
    if not ok:
        raise ExprError(message, code="EXPR_DOMAIN")


def _sqrt(x):
    _domain(x >= 0, "sqrt of a negative number")
    return x.sqrt()


def _sin(x):
    """sin(x), x in radians."""
    with localcontext() as c:
        c.prec += 8
        two_pi = 2 * _PI
        x = x % two_pi
        if x > _PI:
            x -= two_pi
        elif x < -_PI:
            x += two_pi
        total, term, n, x2 = x, x, 1, x * x
        while True:
            term = -term * x2 / ((2 * n) * (2 * n + 1))
            n += 1
            nxt = total + term
            if nxt == total:
                break
            total = nxt
    return +total


def _atan(x):
    with localcontext() as c:
        c.prec += 8
        sign = -1 if x < 0 else 1
        x = abs(x)
        invert = x > 1
        if invert:
            x = 1 / x
        halvings = 0
        while x > Decimal("0.1"):          # atan(x) = 2·atan(x / (1 + √(1 + x²)))
            x = x / (1 + (1 + x * x).sqrt())
            halvings += 1
        total, term, n, x2 = x, x, 1, x * x
        while True:
            term = -term * x2
            nxt = total + term / (2 * n + 1)
            n += 1
            if nxt == total:
                break
            total = nxt
        total *= 2 ** halvings
        if invert:
            total = _PI / 2 - total
    return +(sign * total)


def _asin(x):
    _domain(-1 <= x <= 1, "asin needs a value between -1 and 1")
    if abs(x) == 1:
        return +(x * _PI / 2)
    return _atan(x / (1 - x * x).sqrt())


def _arc(chord, rise):
    """Circle through both ends of `chord` and the top point `rise` above its middle -> (radius, angle)."""
    _domain(chord > 0 and rise > 0, "chord and rise must be positive")
    half = chord / 2
    radius = (rise * rise + half * half) / (2 * rise)
    angle = 2 * _asin(half / radius)
    if rise > half:                       # more than half a circle
        angle = 2 * _PI - angle
    return radius, angle


def _arc_length(chord, rise):
    radius, angle = _arc(chord, rise)
    return radius * angle


def _segment_area(chord, rise):
    radius, angle = _arc(chord, rise)
    return radius * radius / 2 * (angle - _sin(angle))


FUNCTIONS = {
    "min": (lambda *a: min(a), 1, None),
    "max": (lambda *a: max(a), 1, None),
    "abs": (lambda x: abs(x), 1, 1),
    "round": (_round, 1, 2),
    "ceil": (lambda x: x.to_integral_value(rounding=ROUND_CEILING), 1, 1),
    "floor": (lambda x: x.to_integral_value(rounding=ROUND_FLOOR), 1, 1),
    "round_to": (lambda x, step: _q(x, step, ROUND_HALF_UP), 2, 2),
    "ceil_to": (lambda x, step: _q(x, step, ROUND_CEILING), 2, 2),
    "floor_to": (lambda x, step: _q(x, step, ROUND_FLOOR), 2, 2),
    "lookup": (_lookup(True), 4, None),      # x <= threshold
    "lookup_lt": (_lookup(False), 4, None),  # x <  threshold
    "clamp": (lambda x, lo, hi: max(lo, min(hi, x)), 3, 3),
    "pi": (lambda: +_PI, 0, 0),
    "sqrt": (_sqrt, 1, 1),
    "sin": (_sin, 1, 1),                              # radians
    "cos": (lambda x: _sin(x + _PI / 2), 1, 1),
    "tan": (lambda x: _sin(x) / _sin(x + _PI / 2), 1, 1),
    "atan": (_atan, 1, 1),
    "asin": (_asin, 1, 1),
    "acos": (lambda x: _PI / 2 - _asin(x), 1, 1),
    "rad": (lambda d: d * _PI / 180, 1, 1),           # degrees -> radians
    "deg": (lambda r: r * 180 / _PI, 1, 1),           # radians -> degrees
    "arc_radius": (lambda c, r: _arc(c, r)[0], 2, 2),  # arch: chord (width) and rise (height)
    "arc_angle": (lambda c, r: _arc(c, r)[1], 2, 2),   # radians
    "arc_length": (_arc_length, 2, 2),
    "segment_area": (_segment_area, 2, 2),
}
LAZY_FUNCTIONS = {"if": 3}


# ---------------------------------------------------------------- parser
class _Parser:
    def __init__(self, tokens: list[Token]):
        self.t = tokens
        self.i = 0
        self.nodes = 0

    def peek(self) -> Token:
        return self.t[self.i]

    def take(self) -> Token:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, value: str) -> Token:
        tok = self.take()
        if tok.value != value:
            raise ExprError(f"Expected {value!r} at {tok.pos}", code="EXPR_SYNTAX", position=tok.pos)
        return tok

    def node(self, *parts, depth: int):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ExprError("Expression too complex", code="EXPR_TOO_COMPLEX")
        if depth > MAX_DEPTH:
            raise ExprError("Expression nested too deeply", code="EXPR_TOO_COMPLEX")
        return parts

    def parse(self):
        tree = self.or_(0)
        if self.peek().kind != "end":
            tok = self.peek()
            raise ExprError(f"Unexpected {tok.value!r} at {tok.pos}", code="EXPR_SYNTAX", position=tok.pos)
        return tree

    def or_(self, d):
        left = self.and_(d + 1)
        while self.peek().value == "or":
            self.take()
            left = self.node("or", left, self.and_(d + 1), depth=d)
        return left

    def and_(self, d):
        left = self.not_(d + 1)
        while self.peek().value == "and":
            self.take()
            left = self.node("and", left, self.not_(d + 1), depth=d)
        return left

    def not_(self, d):
        if self.peek().value == "not":
            self.take()
            return self.node("not", self.not_(d + 1), depth=d)
        return self.cmp(d + 1)

    def cmp(self, d):
        left = self.sum(d + 1)
        if self.peek().value in ("<", "<=", ">", ">=", "==", "!="):
            op = self.take().value
            left = self.node("cmp", op, left, self.sum(d + 1), depth=d)
        return left

    def sum(self, d):
        left = self.term(d + 1)
        while self.peek().value in ("+", "-"):
            op = self.take().value
            left = self.node("bin", op, left, self.term(d + 1), depth=d)
        return left

    def term(self, d):
        left = self.unary(d + 1)
        while self.peek().value in ("*", "/", "%"):
            op = self.take().value
            left = self.node("bin", op, left, self.unary(d + 1), depth=d)
        return left

    def unary(self, d):
        if self.peek().value in ("-", "+"):
            op = self.take().value
            operand = self.unary(d + 1)
            return operand if op == "+" else self.node("neg", operand, depth=d)
        return self.atom(d + 1)

    def atom(self, d):
        tok = self.take()
        if tok.kind == "num":
            return self.node("num", Decimal(tok.value), depth=d)
        if tok.kind == "kw" and tok.value in ("true", "false"):
            return self.node("bool", tok.value == "true", depth=d)
        if tok.kind == "name":
            if self.peek().value == "(":
                self.take()
                args = []
                if self.peek().value != ")":
                    args.append(self.or_(d + 1))
                    while self.peek().value == ",":
                        self.take()
                        args.append(self.or_(d + 1))
                self.expect(")")
                self._check_call(tok, len(args))
                return self.node("call", tok.value, tuple(args), depth=d)
            return self.node("name", tok.value, depth=d)
        if tok.value == "(":
            inner = self.or_(d + 1)
            self.expect(")")
            return inner
        raise ExprError(f"Unexpected {tok.value or 'end of expression'!r} at {tok.pos}", code="EXPR_SYNTAX",
                        position=tok.pos)

    @staticmethod
    def _check_call(tok: Token, argc: int) -> None:
        if tok.value in LAZY_FUNCTIONS:
            if argc != LAZY_FUNCTIONS[tok.value]:
                raise ExprError(f"{tok.value}() takes {LAZY_FUNCTIONS[tok.value]} arguments", code="EXPR_ARGS",
                                position=tok.pos)
            return
        if tok.value not in FUNCTIONS:
            raise ExprError(f"Unknown function {tok.value}()", code="EXPR_UNKNOWN_FUNCTION", position=tok.pos)
        _, lo, hi = FUNCTIONS[tok.value]
        if argc < lo or (hi is not None and argc > hi):
            raise ExprError(f"Wrong number of arguments for {tok.value}()", code="EXPR_ARGS", position=tok.pos)


class Expression:
    """A compiled expression. `names` = variables it reads."""

    __slots__ = ("source", "tree", "names")

    def __init__(self, source: str):
        self.source = source
        self.tree = _Parser(tokenize(source)).parse()
        self.names = frozenset(_names(self.tree))

    def evaluate(self, env: dict[str, object]):
        with localcontext() as ctx:
            ctx.prec = 34
            try:
                return _eval(self.tree, env)
            except (DivisionByZero, InvalidOperation, ZeroDivisionError):
                raise ExprError("Division by zero or invalid arithmetic", code="EXPR_MATH")

    def __repr__(self) -> str:
        return f"Expression({self.source!r})"


def compile_expr(source) -> Expression:
    if isinstance(source, (int, Decimal)):
        source = str(source)
    return Expression(str(source))


def _names(tree) -> set[str]:
    kind = tree[0]
    if kind == "name":
        return {tree[1]}
    if kind in ("num", "bool"):
        return set()
    if kind == "call":
        out = set()
        for a in tree[2]:
            out |= _names(a)
        return out
    out = set()
    for part in tree[1:]:
        if isinstance(part, tuple):
            out |= _names(part)
    return out


def _num(value, what: str) -> Decimal:
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise ExprError(f"{what} is not a number", code="EXPR_TYPE")


def _eval(t, env):
    kind = t[0]
    if kind == "num":
        return t[1]
    if kind == "bool":
        return t[1]
    if kind == "name":
        if t[1] not in env:
            raise ExprError(f"Unknown name {t[1]}", code="EXPR_UNKNOWN_NAME")
        value = env[t[1]]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = Decimal(str(value))
        return value
    if kind == "neg":
        return -_num(_eval(t[1], env), "operand")
    if kind == "bin":
        op, a, b = t[1], _num(_eval(t[2], env), "left operand"), _num(_eval(t[3], env), "right operand")
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise ExprError("Division by zero", code="EXPR_MATH")
        return a / b if op == "/" else a % b
    if kind == "cmp":
        op, a, b = t[1], _eval(t[2], env), _eval(t[3], env)
        if op in ("==", "!="):
            a, b = (_num(a, "left"), _num(b, "right")) if not (isinstance(a, bool) and isinstance(b, bool)) else (a, b)
            return (a == b) if op == "==" else (a != b)
        a, b = _num(a, "left operand"), _num(b, "right operand")
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if kind == "and":
        return _truthy(_eval(t[1], env)) and _truthy(_eval(t[2], env))
    if kind == "or":
        return _truthy(_eval(t[1], env)) or _truthy(_eval(t[2], env))
    if kind == "not":
        return not _truthy(_eval(t[1], env))
    if kind == "call":
        name, args = t[1], t[2]
        if name == "if":
            return _eval(args[1], env) if _truthy(_eval(args[0], env)) else _eval(args[2], env)
        fn = FUNCTIONS[name][0]
        return fn(*[_num(_eval(a, env), f"argument of {name}") for a in args])
    raise ExprError(f"Bad node {kind}")


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return _num(value, "condition") != 0


def to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise ExprError("Not a number", code="EXPR_TYPE")
