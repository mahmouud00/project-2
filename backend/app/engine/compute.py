"""Evaluate a published model definition ("snapshot") for given inputs.

Everything specific to a profile system (deductions, constants, counts,
which material each piece is cut from) comes from the snapshot data. This
module only knows the generic rules:

* the API speaks millimetres; a system may author its formulas in cm or mm;
* manufacturing size = opening size - installation clearance (both recorded);
* constants = library value (or company override) + company calibration delta;
* formulas are evaluated in dependency order; cycles/unknown names are errors;
* a piece's key can be used in another piece's (or glass, accessory, check, drawing) expression: it means that
  piece's length formula, exactly as if it were written there (system unit, before any rounding);
* generic sanity checks on every cut piece and glass pane.

Snapshot layout (see app/modules/library/publish.py):
{
  "system": {"code", "name", "material_type", "unit": "mm"|"cm", "rounding_step_mm", "rounding_mode"},
  "constants": {name: {"value": "12.5", "label", "unit"}},
  "materials": {code: {"name", "kind", "unit", "bar_length_mm", "min_piece_mm"}},
  "model": {"code", "name", "category", "params": [...], "formulas": [...], "pieces": [...],
            "glass": [...], "accessories": [...], "validations": [...], "drawing": [...]}
}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.engine.expr import NAME_ALIASES, Expression, ExprError, compile_expr, to_decimal

UNIT_FACTOR = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}
# the Arabic spellings (العرض، الارتفاع، ...) are reserved too, so no parameter or formula can shadow them
# Arabic names for the places a message points to (the library author reads them)
SECTION_AR = {"pieces": "القطعة", "glass": "الزجاج", "accessories": "الإكسسوار", "purchase": "طلبية الشراء"}
FIELD_AR = {"length_expr": "معادلة الطول", "qty_expr": "العدد", "angle_left": "زاوية 1", "angle_right": "زاوية 2",
            "width_expr": "معادلة العرض", "height_expr": "معادلة الارتفاع"}


def _ar(name: str) -> str:
    """install_clearance_width -> خلوص_العرض (the Arabic spelling of a built-in name)."""
    return next((a for a, e in NAME_ALIASES.items() if e == name), name)


RESERVED = {"opening_width", "opening_height", "width", "height"} | set(NAME_ALIASES)
REQUIRED_CONSTANTS = ("install_clearance_width", "install_clearance_height")
ROUNDING = {"half_up": ROUND_HALF_UP, "up": ROUND_CEILING, "down": ROUND_FLOOR}
LENGTH_UNITS = {"length"}


class CalcError(Exception):
    def __init__(self, message: str, *, code: str = "CALC_ERROR", where: str | None = None):
        super().__init__(message)
        self.code = code
        self.where = where

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "where": self.where}


@dataclass
class Issue:
    level: str  # error | warning
    code: str
    message: str
    where: str | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "where": self.where}


@dataclass
class Result:
    inputs: dict
    constants: dict
    values: dict
    pieces: list[dict] = field(default_factory=list)
    glass: list[dict] = field(default_factory=list)
    accessories: list[dict] = field(default_factory=list)
    drawing: list[dict] = field(default_factory=list)
    purchase: list[dict] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "inputs": _jsonify(self.inputs), "constants": _jsonify(self.constants),
            "values": _jsonify(self.values), "pieces": _jsonify(self.pieces), "glass": _jsonify(self.glass),
            "accessories": _jsonify(self.accessories), "drawing": _jsonify(self.drawing),
            "purchase": _jsonify(self.purchase), "issues": [i.as_dict() for i in self.issues],
        }


def _jsonify(value):
    if isinstance(value, Decimal):
        return _dec_str(value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


def _dec_str(d: Decimal) -> str:
    d = d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP).normalize()
    return format(d, "f")


def _compile(source, where: str) -> Expression:
    try:
        return compile_expr(source)
    except ExprError as e:
        raise CalcError(f"{where}: {e}", code=e.code, where=where)


def _eval(expr: Expression, env: dict, where: str):
    try:
        return expr.evaluate(env)
    except ExprError as e:
        raise CalcError(f"{where}: {e}", code=e.code, where=where)


def _int_qty(value, where: str, issues: list[Issue]) -> int:
    d = to_decimal(value)
    if d != d.to_integral_value():
        issues.append(Issue("error", "QTY_NOT_INTEGER", f"العدد {d} لازم يكون رقم صحيح", where))
        return int(d.to_integral_value(rounding=ROUND_CEILING))
    if d < 0:
        issues.append(Issue("error", "QTY_NEGATIVE", f"العدد {d} بالسالب", where))
        return 0
    return int(d)


# ---------------------------------------------------------------- definition check
def check_definition(snapshot: dict) -> list[str]:
    """Static validation used before a model can be published. Returns error messages."""
    errors: list[str] = []
    model = snapshot.get("model", {})
    constants = snapshot.get("constants", {})
    unit = snapshot.get("system", {}).get("unit", "mm")
    if unit not in UNIT_FACTOR:
        errors.append(f"وحدة السيستم {unit!r} مش مدعومة")
    for name in REQUIRED_CONSTANTS:
        if name not in constants:
            errors.append(f"ثابت السيستم {_ar(name)} لازم يكون موجود")
    params = [p["name"] for p in model.get("params", [])]
    formula_keys = [f["key"] for f in model.get("formulas", [])]
    seen: set[str] = set()
    for name in list(constants) + params + formula_keys:
        if name in seen:
            errors.append(f"الاسم {name} متعرّف مرتين")
        seen.add(name)
        if name in RESERVED and name not in constants:
            errors.append(f"الاسم {name} محجوز (اسم جاهز في البرنامج)")
    known_formulas = set(constants) | set(params) | set(formula_keys) | RESERVED
    piece_keys = [p.get("key") for p in model.get("pieces", []) if p.get("key")]
    for key in piece_keys:
        if key in known_formulas:
            errors.append(f"اسم القطعة {key} هو نفس اسم ثابت أو متغير أو قيمة مساعدة")
    if len(set(piece_keys)) != len(piece_keys):
        errors.append("في قطعتين ليهم نفس الاسم: " + "، ".join(sorted({k for k in piece_keys if piece_keys.count(k) > 1})))
    glass_names = set(glass_dims(model.get("glass", []))) | set(glass_kind_names(known_formulas | set(piece_keys)))
    for name in sorted(glass_names & (known_formulas | set(piece_keys))):
        errors.append(f"اسم مقاس الزجاج {name} هو نفس اسم تاني")
    known = known_formulas | set(piece_keys) | glass_names
    materials = snapshot.get("materials", {})

    def chk(source, where, required=True, names=None):
        if source in (None, "") and not required:
            return
        try:
            e = compile_expr(source)
        except ExprError as ex:
            errors.append(f"{where}: {ex}")
            return
        missing = e.names - (known if names is None else names)
        if missing:
            errors.append(f"{where}: أسامي مش معروفة: {'، '.join(sorted(missing))}")

    for f in model.get("formulas", []):
        chk(f.get("expr"), f"المعادلة {f['key']}", names=known_formulas)   # pieces come after the formulas
    try:
        _formula_order(model.get("formulas", []))
    except CalcError as e:
        errors.append(str(e))
    cycle = _piece_cycle(model.get("pieces", []), model.get("glass", []))
    if cycle:
        errors.append(cycle)
    for section, exprs in (("pieces", ("length_expr", "qty_expr", "angle_left", "angle_right")),
                           ("glass", ("width_expr", "height_expr", "qty_expr")),
                           ("accessories", ("qty_expr",)), ("purchase", ("length_expr", "qty_expr"))):
        for item in model.get(section, []):
            where = f"{SECTION_AR[section]} {item.get('key')}"
            for k in exprs:
                chk(item.get(k, "0" if k.startswith("angle") else None), f"{where}، {FIELD_AR.get(k, k)}")
            chk(item.get("condition"), f"{where}، الشرط", required=False)
            if section == "glass":
                chk(item.get("area_expr"), f"{where}، المساحة", required=False)
            code = item.get("material_code")
            if section != "glass" and code not in materials:
                errors.append(f"{where}: الخامة {code} مش موجودة في المكتبة")
            if section == "glass" and code and code not in materials:
                errors.append(f"{where}: الخامة {code} مش موجودة في المكتبة")
            if section == "purchase" and code in materials and materials[code].get("kind") not in ("profile", "reinforcement"):
                errors.append(f"{where}: طلبية الشراء للقطاعات والحديد بس؛ {code} بيتطلب من تاب الإكسسوار")
    for i, v in enumerate(model.get("validations", [])):
        chk(v.get("expr"), f"التحقق رقم {i + 1}")
    for i, d in enumerate(model.get("drawing", [])):
        for k in ("x", "y", "w", "h"):
            chk(d.get(k, "0"), f"الرسمة رقم {i + 1}، {k}")
    return errors


GLASS_W, GLASS_H = "_عرض", "_ارتفاع"
# نوع الزجاج on every window: سنجل or دبل. In formulas: «نوع_الزجاج == دبل»; a glass row can be for one of them only.
GLASS_KIND = "نوع_الزجاج"
GLASS_KINDS = {"سنجل": Decimal(1), "دبل": Decimal(2)}
KIND_OF_ROW = {"single": Decimal(1), "double": Decimal(2)}


def glass_kind_names(taken: set) -> dict:
    """The names a model can use for the glass kind (one it defines itself keeps its own meaning)."""
    return {k: v for k, v in {GLASS_KIND: Decimal(1), **GLASS_KINDS}.items() if k not in taken}


def glass_dims(glass: list[dict]) -> dict[str, tuple[dict, str]]:
    """{«زجاج_الضلفة_عرض»: (the glass row, "width_expr"), «زجاج_الضلفة_ارتفاع»: (…, "height_expr")}: a pane's width
    and height are names other expressions can use, like a piece's key is its length."""
    out = {}
    for g in glass:
        if g.get("key"):
            out[g["key"] + GLASS_W] = (g, "width_expr")
            out[g["key"] + GLASS_H] = (g, "height_expr")
    return out


def _piece_cycle(pieces: list[dict], glass: list[dict] | None = None) -> str | None:
    try:
        _piece_order(pieces, glass)
    except CalcError as e:
        return str(e)
    return None


def _piece_order(pieces: list[dict], glass: list[dict] | None = None) -> list[str]:
    """Piece keys (and glass widths / heights) in the order they can be worked out: each after the ones it uses.
    One whose formula does not compile is left out (its own error is reported where it is evaluated)."""
    exprs = {}
    for p in pieces:
        if p.get("key") and p.get("length_expr"):
            try:
                exprs[p["key"]] = compile_expr(p["length_expr"])
            except ExprError:
                pass
    for name, (g, field) in glass_dims(glass or []).items():
        if g.get(field):
            try:
                exprs[name] = compile_expr(g[field])
            except ExprError:
                pass
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(key: str, stack: list[str]):
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise CalcError("قطع (أو زجاج) بتعتمد على بعض في دايرة: " + " ← ".join(stack + [key]), code="PIECE_CYCLE")
        state[key] = 1
        for dep in sorted(exprs[key].names):
            if dep in exprs:
                visit(dep, stack + [key])
        state[key] = 2
        order.append(key)

    for key in exprs:
        visit(key, [])
    return order


def _formula_order(formulas: list[dict]) -> list[tuple[dict, Expression]]:
    compiled = {f["key"]: (f, _compile(f["expr"], f"المعادلة {f['key']}")) for f in formulas}
    order: list[tuple[dict, Expression]] = []
    state: dict[str, int] = {}

    def visit(key: str, stack: list[str]):
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise CalcError("معادلات بتعتمد على بعض في دايرة: " + " ← ".join(stack + [key]), code="FORMULA_CYCLE")
        state[key] = 1
        for dep in sorted(compiled[key][1].names):
            if dep in compiled:
                visit(dep, stack + [key])
        state[key] = 2
        order.append(compiled[key])

    for key in compiled:
        visit(key, [])
    return order


# ---------------------------------------------------------------- evaluation
def _param_value(p: dict, raw, issues: list[Issue]):
    name, ptype = p["name"], p.get("type", "number")
    if raw is None:
        raw = p.get("default")
    if raw is None:
        raise CalcError(f"المتغير {name} مطلوب", code="PARAM_REQUIRED", where=name)
    if ptype == "bool":
        if isinstance(raw, bool):
            return raw
        if raw in (0, 1, "0", "1", "true", "false"):
            return raw in (1, "1", "true")
        raise CalcError(f"المتغير {name} لازم يبقى نعم أو لا", code="PARAM_INVALID", where=name)
    try:
        value = to_decimal(raw)
    except Exception:
        raise CalcError(f"المتغير {name} لازم يبقى رقم", code="PARAM_INVALID", where=name)
    if ptype in ("int", "count") and value != value.to_integral_value():
        raise CalcError(f"المتغير {name} لازم يبقى رقم صحيح", code="PARAM_INVALID", where=name)
    if ptype == "choice":
        allowed = [to_decimal(c["value"]) for c in p.get("choices", [])]
        if value not in allowed:
            raise CalcError(f"المتغير {name} لازم يبقى واحد من {allowed}", code="PARAM_INVALID", where=name)
    if p.get("min") is not None and value < to_decimal(p["min"]):
        raise CalcError(f"المتغير {name} أقل من {p['min']}", code="PARAM_RANGE", where=name)
    if p.get("max") is not None and value > to_decimal(p["max"]):
        raise CalcError(f"المتغير {name} أكبر من {p['max']}", code="PARAM_RANGE", where=name)
    return value


def effective_constants(snapshot: dict, calibration: dict | None = None, overrides: dict | None = None) -> dict:
    """library value -> company override (replaces) -> + calibration delta."""
    out = {}
    for name, c in snapshot.get("constants", {}).items():
        value = to_decimal((overrides or {}).get(name, c["value"]))
        value += to_decimal((calibration or {}).get(name, 0))
        out[name] = value
    unknown = set(calibration or {}) | set(overrides or {})
    unknown -= set(out)
    if unknown:
        raise CalcError(f"معايرة لثوابت مش موجودة: {'، '.join(sorted(unknown))}", code="CALIBRATION_UNKNOWN")
    return out


def _round_mm(value: Decimal, step: Decimal, mode: str) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUNDING.get(mode, ROUND_HALF_UP)) * step


def calculate(snapshot: dict, *, opening_width_mm, opening_height_mm, params: dict | None = None,
              calibration: dict | None = None, overrides: dict | None = None) -> Result:
    system = snapshot.get("system", {})
    model = snapshot["model"]
    materials = snapshot.get("materials", {})
    factor = UNIT_FACTOR[system.get("unit", "mm")]
    step = to_decimal(system.get("rounding_step_mm", "0"))
    mode = system.get("rounding_mode", "half_up")
    issues: list[Issue] = []
    params = params or {}

    own = {p["name"] for p in model.get("params", [])}
    unknown_params = set(params) - own - ({GLASS_KIND} if GLASS_KIND not in own else set())
    if unknown_params:
        raise CalcError(f"متغيرات مش موجودة في النموذج: {'، '.join(sorted(unknown_params))}", code="PARAM_UNKNOWN")

    consts = effective_constants(snapshot, calibration, overrides)
    for name in REQUIRED_CONSTANTS:
        if name not in consts:
            raise CalcError(f"ثابت السيستم {_ar(name)} مش موجود", code="CONSTANT_MISSING", where=name)

    ow, oh = to_decimal(opening_width_mm), to_decimal(opening_height_mm)
    if ow <= 0 or oh <= 0:
        raise CalcError("مقاس الفتحة لازم يكون أكبر من صفر", code="OPENING_INVALID")
    env: dict = dict(consts)
    env["opening_width"] = ow / factor
    env["opening_height"] = oh / factor
    env["width"] = env["opening_width"] - consts["install_clearance_width"]
    env["height"] = env["opening_height"] - consts["install_clearance_height"]
    if env["width"] <= 0 or env["height"] <= 0:
        issues.append(Issue("error", "MANUFACTURING_SIZE_INVALID", "مقاس التصنيع بعد خلوص التركيب صفر أو بالسالب"))

    inputs = {"opening_width_mm": ow, "opening_height_mm": oh,
              "width_mm": env["width"] * factor, "height_mm": env["height"] * factor}
    for p in model.get("params", []):
        env[p["name"]] = _param_value(p, params.get(p["name"]), issues)
        inputs[p["name"]] = env[p["name"]]
    for name, value in glass_kind_names(set(env) | {f["key"] for f in model.get("formulas", [])}).items():
        env[name] = value
    if GLASS_KIND not in own:
        kind = to_decimal(params.get(GLASS_KIND, 1))
        if kind not in GLASS_KINDS.values():
            raise CalcError("نوع الزجاج لازم يبقى سنجل (1) أو دبل (2)", code="PARAM_INVALID", where=GLASS_KIND)
        env[GLASS_KIND] = kind
        inputs[GLASS_KIND] = kind
        inputs["glass_kind"] = "دبل" if kind == 2 else "سنجل"

    values: dict = {}
    for f, expr in _formula_order(model.get("formulas", [])):
        val = _eval(expr, env, f"المعادلة {f['key']}")
        env[f["key"]] = val
        unit = f.get("unit", "number")
        values[f["key"]] = val * factor if unit in LENGTH_UNITS and not isinstance(val, bool) else val

    def cond(item, where) -> bool:
        for_kind = KIND_OF_ROW.get(item.get("for_kind") or "")           # a glass row for سنجل or دبل only
        if for_kind is not None and env.get(GLASS_KIND, Decimal(1)) != for_kind:
            return False
        c = item.get("condition")
        if c in (None, ""):
            return True
        v = _eval(_compile(c, where), env, where)
        return bool(v) if isinstance(v, bool) else v != 0

    result = Result(inputs, consts, values, issues=issues)

    # each piece's length (system unit, exact) under its key, so other expressions can use it: worked out for the
    # pieces that are made and for any piece another expression names (even if it is not made itself)
    pieces = {p["key"]: p for p in model.get("pieces", [])}
    dims = glass_dims(model.get("glass", []))           # each pane's width / height, also usable by name
    clash = (set(pieces) | set(dims)) & (set(env) | set(values))
    if clash:
        raise CalcError(f"اسم القطعة هو نفس اسم ثابت أو متغير أو قيمة مساعدة: {'، '.join(sorted(clash))}",
                        code="NAME_CLASH")
    used = set()
    for section in ("pieces", "glass", "accessories", "validations", "drawing", "purchase"):
        for item in model.get(section, []):
            for k in ("length_expr", "qty_expr", "angle_left", "angle_right", "condition", "width_expr", "height_expr",
                      "area_expr", "expr", "x", "y", "w", "h"):
                if item.get(k) not in (None, ""):
                    try:
                        used |= compile_expr(item[k]).names & (set(pieces) | set(dims))
                    except ExprError:
                        pass
    try:
        order = _piece_order(model.get("pieces", []), model.get("glass", []))
    except CalcError as e:
        raise CalcError(str(e), code=e.code)
    for key in order:
        if key in dims:
            g, field = dims[key]
            where = f"الزجاج {g['key']}"
            if key in used or cond(g, where + "، الشرط"):
                env[key] = to_decimal(_eval(_compile(g[field], where), env, where))
            continue
        item = pieces[key]
        where = f"القطعة {key}"
        if key in used or cond(item, where + "، الشرط"):
            env[key] = to_decimal(_eval(_compile(item["length_expr"], where), env, where))

    for item in model.get("pieces", []):
        where = f"القطعة {item['key']}"
        if not cond(item, where + "، الشرط"):
            continue
        if item["key"] not in env:      # its formula did not compile: report it here
            env[item["key"]] = to_decimal(_eval(_compile(item["length_expr"], where), env, where))
        exact = to_decimal(env[item["key"]]) * factor
        qty = _int_qty(_eval(_compile(item["qty_expr"], where), env, where), where, issues)
        if qty == 0:
            continue
        length = _round_mm(exact, step, mode)
        mat = materials.get(item["material_code"], {})
        piece = {
            "key": item["key"], "label": item.get("label", item["key"]), "role": item.get("role"),
            "element": item.get("element"), "side": item.get("side"),
            "material_code": item["material_code"], "material_name": mat.get("name"),
            "length_mm": length, "length_exact_mm": exact, "qty": qty,
            "angle_left": to_decimal(_eval(_compile(item.get("angle_left", "90"), where), env, where)),
            "angle_right": to_decimal(_eval(_compile(item.get("angle_right", "90"), where), env, where)),
        }
        if length <= 0:
            issues.append(Issue("error", "PIECE_NOT_POSITIVE", f"{piece['label']}: الطول {length} مم", where))
        elif mat.get("min_piece_mm") and length < to_decimal(mat["min_piece_mm"]):
            issues.append(Issue("error", "PIECE_TOO_SHORT",
                                f"{piece['label']}: {length} مم أقصر من أقل طول {mat['min_piece_mm']} مم", where))
        if mat.get("bar_length_mm") and length > to_decimal(mat["bar_length_mm"]):
            issues.append(Issue("error", "PIECE_LONGER_THAN_BAR",
                                f"{piece['label']}: {length} مم أطول من العود {mat['bar_length_mm']} مم", where))
        result.pieces.append(piece)

    for item in model.get("glass", []):
        where = f"الزجاج {item['key']}"
        if not cond(item, where + "، الشرط"):
            continue
        wk, hk = item["key"] + GLASS_W, item["key"] + GLASS_H
        if wk not in env:
            env[wk] = to_decimal(_eval(_compile(item["width_expr"], where), env, where))
        if hk not in env:
            env[hk] = to_decimal(_eval(_compile(item["height_expr"], where), env, where))
        w = _round_mm(to_decimal(env[wk]) * factor, step, mode)
        h = _round_mm(to_decimal(env[hk]) * factor, step, mode)
        qty = _int_qty(_eval(_compile(item["qty_expr"], where), env, where), where, issues)
        if qty == 0:
            continue
        if w <= 0 or h <= 0:
            issues.append(Issue("error", "GLASS_NOT_POSITIVE", f"{item.get('label', item['key'])}: {w}×{h} مم", where))
        if w > inputs["opening_width_mm"] or h > inputs["opening_height_mm"]:
            issues.append(Issue("error", "GLASS_LARGER_THAN_OPENING",
                                f"{item.get('label', item['key'])}: {w}×{h} مم أكبر من الفتحة", where))
        # width × height is the sheet the pane is cut from; a shaped pane gives its real area (area_expr)
        area_mm2 = w * h
        if item.get("area_expr"):
            area_mm2 = to_decimal(_eval(_compile(item["area_expr"], where + "، المساحة"), env, where)) * factor * factor
            if area_mm2 <= 0 or area_mm2 > w * h:
                issues.append(Issue("error", "GLASS_AREA_INVALID",
                                    f"{item.get('label', item['key'])}: المساحة لازم تبقى أكبر من صفر ومش أكبر من العرض × الارتفاع", where))
        result.glass.append({"key": item["key"], "label": item.get("label", item["key"]),
                             "material_code": item.get("material_code"), "width_mm": w, "height_mm": h, "qty": qty,
                             "area_m2": (area_mm2 * qty / Decimal(1_000_000)), "shaped": bool(item.get("area_expr"))})

    for item in model.get("accessories", []):
        where = f"الإكسسوار {item['key']}"
        if not cond(item, where + "، الشرط"):
            continue
        qty = to_decimal(_eval(_compile(item["qty_expr"], where), env, where))
        unit = materials.get(item["material_code"], {}).get("unit", "pcs")
        if unit in ("pcs", "set") and qty != qty.to_integral_value():
            issues.append(Issue("error", "QTY_NOT_INTEGER", f"العدد {qty} لازم يكون رقم صحيح", where))
        if qty < 0:
            issues.append(Issue("error", "QTY_NEGATIVE", f"العدد {qty} بالسالب", where))
        if qty == 0:
            continue
        result.accessories.append({"key": item["key"], "material_code": item["material_code"],
                                   "material_name": materials.get(item["material_code"], {}).get("name"),
                                   "unit": unit, "qty": qty})

    for i, v in enumerate(model.get("validations", [])):
        where = f"التحقق رقم {i + 1}"
        if not _eval(_compile(v["expr"], where), env, where):
            issues.append(Issue(v.get("level", "error"), v.get("code", "RULE_FAILED"), v.get("message", v["expr"]),
                                where))

    # generic sash/frame relation: any 'sash' piece longer than the matching frame side
    frame_max = max((p["length_mm"] for p in result.pieces if p.get("role") == "frame"), default=None)
    for p in result.pieces:
        if p.get("role") == "sash" and frame_max is not None and p["length_mm"] > frame_max:
            issues.append(Issue("error", "SASH_LARGER_THAN_FRAME", f"{p['label']}: أطول من الحلق", p["key"]))

    # حساب طلبية الشراء: the length each piece takes from the bar when buying (the cut list keeps the pieces)
    for item in model.get("purchase", []):
        where = f"طلبية الشراء {item['key']}"
        if not cond(item, where + "، الشرط"):
            continue
        qty = _int_qty(_eval(_compile(item.get("qty_expr", "1"), where), env, where), where, issues)
        if qty == 0:
            continue
        length = _round_mm(to_decimal(_eval(_compile(item["length_expr"], where), env, where)) * factor, step, mode)
        mat = materials.get(item["material_code"], {})
        if length <= 0:
            issues.append(Issue("error", "PURCHASE_NOT_POSITIVE", f"{item.get('label') or item['key']}: الطول {length} مم", where))
        result.purchase.append({"key": item["key"], "label": item.get("label") or item["key"],
                                "material_code": item["material_code"], "material_name": mat.get("name"),
                                "length_mm": length, "qty": qty})

    for i, d in enumerate(model.get("drawing", [])):
        where = f"الرسمة رقم {i + 1}"
        if not cond(d, where + "، الشرط"):
            continue
        el = {"type": d.get("type", "rect"), "label": d.get("label"), "opening": d.get("opening")}
        for k in ("x", "y", "w", "h"):
            el[k + "_mm"] = to_decimal(_eval(_compile(d.get(k, "0"), where), env, where)) * factor
        result.drawing.append(el)
    return result
