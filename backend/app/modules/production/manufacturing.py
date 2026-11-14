"""Manufacturing outputs of a work order, built from the frozen engine results
of its items (each item keeps the formula version it was calculated with)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.compute import _jsonify
from app.engine.cutting import optimise
from app.modules.library.models import FormulaSetVersion, ProductModel
from app.modules.library.service import model_image
from app.modules.org.settings import get_company_settings
from app.modules.production.models import WorkOrder, WorkOrderItem
from app.modules.sales.pricing import CostResolver, money


def _sku(material: dict | None, code: str, color: str | None) -> str:
    if material and color and color in material.get("variants", {}):
        return material["variants"][color]
    return code


NO_CUT = {"code": "", "miter_frame_mm": Decimal(0), "miter_sash_mm": Decimal(0), "miter_bead_mm": Decimal(0),
          "saw_kerf_mm": Decimal(0), "bar_start_waste_mm": Decimal(0)}
MITER_ROLE = {"frame": "miter_frame_mm", "sash": "miter_sash_mm", "bead": "miter_bead_mm"}


def system_cutting(db: Session, model_id, cache: dict) -> dict:
    """How the bars of the model's system are cut (its values as they are now: machine settings, not formulas)."""
    from app.modules.library.models import ProfileSystem

    if model_id not in cache:
        model = db.get(ProductModel, model_id)
        system = db.get(ProfileSystem, model.system_id) if model else None
        cache[model_id] = NO_CUT if system is None else {
            "code": system.code, **{k: Decimal(getattr(system, k) or 0) for k in NO_CUT if k != "code"}}
    return cache[model_id]


_ROLE_WORDS = (("حلق", "frame"), ("فريم", "frame"), ("ضلف", "sash"), ("باكت", "bead"), ("frame", "frame"),
               ("sash", "sash"), ("bead", "bead"))


def _role_from_name(piece: dict) -> str | None:
    """A piece saved without a role: its element's (or label's) name says it, as in the model editor."""
    for text in (piece.get("element"), piece.get("label"), piece.get("key"), piece.get("material_name")):
        t = (text or "").strip().replace("أ", "ا").replace("إ", "ا").lower()
        for word in t.replace("_", " ").split():
            word = word[2:] if word.startswith("ال") and len(word) > 3 else word      # «الحلق» is a frame too
            for prefix, role in _ROLE_WORDS:
                if word.startswith(prefix):
                    return role
    return None


def miter_ends(piece: dict) -> int:
    """How many times a 45° piece takes its role's allowance from the bar: a frame (حلق) before and after the
    piece, in any system (sliding or hinged); a sash or a bead once. 0: not a 45° frame / sash / bead piece."""
    role = piece.get("role") if piece.get("role") in MITER_ROLE else _role_from_name(piece)
    if role not in MITER_ROLE:
        return 0
    angles = (piece.get("angle_left"), piece.get("angle_right"))
    if not any(a is not None and abs(Decimal(str(a)) - 45) < Decimal("0.5") for a in angles):
        return 0
    return 2 if role == "frame" else 1


def miter_extra(piece: dict, cut: dict) -> Decimal:
    """What a frame / sash / bead piece cut at 45° takes from the bar beyond its length."""
    ends = miter_ends(piece)
    if not ends:
        return Decimal(0)
    role = piece.get("role") if piece.get("role") in MITER_ROLE else _role_from_name(piece)
    return cut[MITER_ROLE[role]] * ends


def unit_ranges(units) -> str:
    """[1, 1, 2, 3, 5] -> "1–3، 5" (the windows a row of the cut list is for)."""
    nums = sorted(set(int(u) for u in units))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}–{nums[j]}")
        i = j + 1
    return "، ".join(out)


def available_offcuts(db: Session, branch_id, skus=None, lock: bool = False) -> dict[str, list[dict]]:
    """Offcuts in stock at the order's branch, per SKU (locked while an order takes them)."""
    from app.modules.production.models import Offcut

    stmt = select(Offcut).where(Offcut.branch_id == branch_id, Offcut.status == "available")
    if skus is not None:
        stmt = stmt.where(Offcut.sku.in_(list(skus)))
    if lock:
        stmt = stmt.with_for_update()
    out: dict[str, list[dict]] = defaultdict(list)
    for o in db.scalars(stmt.order_by(Offcut.length_mm)):
        out[o.sku].append({"id": str(o.id), "length_mm": o.length_mm})
    return out


def generate_outputs(db: Session, wo: WorkOrder, offcuts: dict[str, list[dict]] | None = None) -> dict:
    """offcuts: stock to cut from first (default: what is available at the order's branch now)."""
    settings = get_company_settings(db, wo.company_id)
    items = list(db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id)
                            .order_by(WorkOrderItem.position)))
    versions: dict[uuid.UUID, dict] = {}
    cut_groups: dict[str, dict] = {}
    glass, accessories, drawings, issues = [], defaultdict(lambda: {"qty": Decimal(0)}), [], []
    # what is bought per SKU: the model's «حساب طلبية الشراء» rows when it has them, else its pieces (each with a
    # saw cut, as the cut list); the cut list itself always comes from the pieces
    buy_groups: dict[str, dict] = {}
    systems: dict = {}
    unit_places: dict[int, str] = {}   # window number -> where it goes on site
    next_unit = 1          # every window of the order gets its own number (شباك 1، 2، …) for the cutter to mark pieces

    for item in items:
        if item.formula_set_version_id not in versions:
            versions[item.formula_set_version_id] = db.get(FormulaSetVersion, item.formula_set_version_id).snapshot
        materials = versions[item.formula_set_version_id]["materials"]
        calc = item.calc
        cut = system_cutting(db, item.model_id, systems)
        ref = f"{item.position}" + (f" ({item.location})" if item.location else "")
        units = list(range(next_unit, next_unit + item.qty))
        next_unit += item.qty
        for u in units:
            unit_places[u] = item.location or ""
        for issue in calc.get("issues", []):
            issues.append({**issue, "item": item.position})
        for p in calc.get("pieces", []):
            mat = materials.get(p["material_code"])
            sku = _sku(mat, p["material_code"], item.color_code)
            g = cut_groups.setdefault(sku, {
                "sku": sku, "material_code": p["material_code"], "material_name": p.get("material_name"),
                "unit": (mat or {}).get("unit", "m"), "bar_length_mm": (mat or {}).get("bar_length_mm"),
                "color": item.color_code, "pieces": defaultdict(lambda: {"qty": 0, "refs": []})})
            g.setdefault("cut", cut)
            key = (p["length_mm"], p["angle_left"], p["angle_right"], p.get("label", p["key"]),
                   p.get("element"), p.get("side"), miter_extra(p, cut), miter_ends(p))
            entry = g["pieces"][key]
            entry["qty"] += int(p["qty"]) * item.qty
            entry["refs"].append(ref)
            entry.setdefault("units", []).extend(u for u in units for _ in range(int(p["qty"])))
        rows = calc.get("purchase") or []
        bought = {r["material_code"] for r in rows}
        # a material the model has purchase rows for is bought by them; any other one by its pieces
        for p, from_rows in [(r, True) for r in rows] + [(p, False) for p in calc.get("pieces", [])
                                                         if p["material_code"] not in bought]:
            mat = materials.get(p["material_code"])
            sku = _sku(mat, p["material_code"], item.color_code)
            b = buy_groups.setdefault(sku, {"sku": sku, "material_code": p["material_code"],
                                            "material_name": p.get("material_name"), "unit": (mat or {}).get("unit", "m"),
                                            "bar_length_mm": (mat or {}).get("bar_length_mm"), "pieces": [],
                                            "from_purchase": False})
            b.setdefault("cut", cut)
            extra = Decimal(0) if from_rows else cut["saw_kerf_mm"] + miter_extra(p, cut)
            b["pieces"].append({"length_mm": Decimal(p["length_mm"]) + extra, "qty": int(p["qty"]) * item.qty})
            b["from_purchase"] = b["from_purchase"] or from_rows
        for gl in calc.get("glass", []):
            code = gl.get("material_code") or item.glass_material_code
            qty = int(gl["qty"]) * item.qty
            glass.append({"item": item.position, "location": item.location, "label": gl.get("label"),
                          "material_code": code, "width_mm": gl["width_mm"], "height_mm": gl["height_mm"],
                          "qty": qty, "area_m2": str(Decimal(gl["width_mm"]) * Decimal(gl["height_mm"]) * qty
                                                     / Decimal(1_000_000))})
        for a in calc.get("accessories", []):
            mat = materials.get(a["material_code"])
            sku = _sku(mat, a["material_code"], item.color_code)
            acc = accessories[sku]
            acc.update({"sku": sku, "material_code": a["material_code"], "material_name": a.get("material_name"),
                        "unit": a.get("unit"), "color": item.color_code})
            acc["qty"] += Decimal(a["qty"]) * item.qty
        model = db.get(ProductModel, item.model_id)
        drawings.append({"item": item.position, "location": item.location, "qty": item.qty, "units": units,
                         "model_code": model.code if model else None, "model_name": model.name if model else None,
                         "model_image_id": str(img) if (img := model_image(model, item.color_code)) else None,
                         "opening_width_mm": str(item.opening_width_mm), "opening_height_mm": str(item.opening_height_mm),
                         "width_mm": calc.get("inputs", {}).get("width_mm"),
                         "height_mm": calc.get("inputs", {}).get("height_mm"),
                         "elements": calc.get("drawing", [])})

    resolver = CostResolver(db)
    if offcuts is None:
        offcuts = available_offcuts(db, wo.branch_id, cut_groups.keys())
    cut_list, optimisation, costs, missing = [], [], [], set()
    cut_total: dict[str, Decimal] = {}
    for sku, g in sorted(cut_groups.items()):
        # (group key is the SKU, so all its pieces share one colour)
        pieces = [{"length_mm": Decimal(k[0]), "angle_left": k[1], "angle_right": k[2], "label": k[3],
                   "element": k[4], "side": k[5], "extra_mm": k[6], "miter_ends": k[7] if k[6] else 0,
                   "qty": v["qty"], "refs": v["refs"],
                   "units": sorted(v.get("units", [])), "windows": unit_ranges(v.get("units", []))}
                  for k, v in g["pieces"].items()]
        pieces.sort(key=lambda p: p["length_mm"], reverse=True)
        cut_list.append({"sku": sku, "material_code": g["material_code"], "material_name": g["material_name"],
                         "pieces": pieces, "total_pieces": sum(p["qty"] for p in pieces),
                         "total_length_mm": sum((p["length_mm"] * p["qty"] for p in pieces), Decimal(0))})
        cut_total[sku] = cut_list[-1]["total_length_mm"]
        cost, _, _ = resolver.resolve(g["material_code"], g["color"])
        if g["bar_length_mm"]:
            cut = g.get("cut") or NO_CUT
            plan = optimise([{"length_mm": p["length_mm"], "qty": p["qty"], "label": p["label"], "side": p["side"],
                              "element": p["element"], "units": p["units"], "extra_mm": p["extra_mm"],
                              "miter_ends": p["miter_ends"],
                              "angle_left": p["angle_left"], "angle_right": p["angle_right"]} for p in pieces],
                            bar_length_mm=Decimal(g["bar_length_mm"]), kerf_mm=cut["saw_kerf_mm"],
                            start_mm=cut["bar_start_waste_mm"], min_offcut_mm=settings.min_reusable_offcut_mm,
                            stock=offcuts.get(sku, []))
            plan["sku"] = sku
            for bar in plan["bars"]:              # the cutter writes «ع 1 - الدور الأول شقة 1» on each piece
                for piece in bar["pieces"]:
                    if piece.get("unit") is not None:
                        piece["location"] = unit_places.get(piece["unit"], "")
            for t in plan["too_long"]:
                issues.append({"level": "error", "code": "PIECE_LONGER_THAN_BAR", "message": f"{sku}: {t['length_mm']} mm",
                               "where": sku})
            optimisation.append(plan)
            consumed_m = plan["new_bars_length_mm"] / 1000      # offcuts were paid by earlier orders
        else:
            consumed_m = cut_list[-1]["total_length_mm"] / 1000
        if cost is None:
            missing.add(g["material_code"])
        else:
            costs.append({"type": "profile", "sku": sku, "qty": consumed_m, "unit": "m", "unit_cost": cost,
                          "amount": money(consumed_m * cost)})

    purchase = []
    planned = {p["sku"]: p for p in optimisation}
    for sku, b in sorted(buy_groups.items()):
        total = sum((p["length_mm"] * p["qty"] for p in b["pieces"]), Decimal(0))
        if not b["from_purchase"]:
            total = cut_total.get(sku, total)              # the pieces themselves, without the saw cuts
        row = {"sku": sku, "material_code": b["material_code"], "material_name": b["material_name"],
               "unit": b["unit"], "total_length_mm": total, "count": sum(p["qty"] for p in b["pieces"]),
               "from_purchase": b["from_purchase"]}
        if not b["from_purchase"] and sku in planned:     # no purchase rows: what the cut plan takes
            plan = planned[sku]
            row.update(bars=plan["bars_count"], bar_length_mm=plan["bar_length_mm"],
                       offcuts_used=len(plan["offcuts_used"]))
        elif b["bar_length_mm"]:
            # the lengths already hold the saw cuts: packed into bars with only the bar ends trimmed
            plan = optimise(b["pieces"], bar_length_mm=Decimal(b["bar_length_mm"]), kerf_mm=Decimal(0),
                            start_mm=(b.get("cut") or NO_CUT)["bar_start_waste_mm"],
                            min_offcut_mm=settings.min_reusable_offcut_mm, stock=offcuts.get(sku, []))
            row.update(bars=plan["bars_count"], bar_length_mm=Decimal(b["bar_length_mm"]),
                       offcuts_used=len(plan["offcuts_used"]), too_long=len(plan["too_long"]))
        purchase.append(row)

    glass_summary: dict[str, Decimal] = defaultdict(Decimal)
    for gl in glass:
        glass_summary[gl["material_code"] or "-"] += Decimal(gl["area_m2"])
    for code, area in glass_summary.items():
        cost, _, _ = resolver.resolve(code, None) if code != "-" else (None, code, None)
        if cost is None:
            missing.add(code)
        else:
            costs.append({"type": "glass", "sku": code, "qty": area, "unit": "m2", "unit_cost": cost,
                          "amount": money(area * cost)})
    acc_list = sorted(accessories.values(), key=lambda a: a["sku"])
    for a in acc_list:
        cost, _, _ = resolver.resolve(a["material_code"], a.pop("color"))
        if cost is None:
            missing.add(a["material_code"])
        else:
            costs.append({"type": "accessory", "sku": a["sku"], "qty": a["qty"], "unit": a.get("unit"),
                          "unit_cost": cost, "amount": money(a["qty"] * cost)})

    total_bars_length = sum((p["total_length_mm"] for p in optimisation), Decimal(0))
    total_waste = sum((p["waste_mm"] for p in optimisation), Decimal(0))
    return _jsonify({
        "cut_list": cut_list,
        "optimisation": optimisation,
        "purchase": purchase,
        "waste_pct": (total_waste / total_bars_length * 100).quantize(Decimal("0.01")) if total_bars_length else Decimal(0),
        "glass": glass,
        "glass_area_by_type": dict(glass_summary),
        "accessories": acc_list,
        "costs": costs,
        "material_cost_total": money(sum((c["amount"] for c in costs), Decimal(0))),
        "missing_costs": sorted(missing),
        "drawings": drawings,
        "issues": issues,
        "settings": {"min_reusable_offcut_mm": settings.min_reusable_offcut_mm,
                     "systems": {c["code"]: {n: str(v) for n, v in c.items() if n != "code"}
                                 for c in systems.values() if c is not NO_CUT}},
    })
