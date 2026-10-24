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
from app.modules.org.settings import get_company_settings
from app.modules.production.models import WorkOrder, WorkOrderItem
from app.modules.sales.pricing import CostResolver, money


def _sku(material: dict | None, code: str, color: str | None) -> str:
    if material and color and color in material.get("variants", {}):
        return material["variants"][color]
    return code


def generate_outputs(db: Session, wo: WorkOrder) -> dict:
    settings = get_company_settings(db, wo.company_id)
    items = list(db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id)
                            .order_by(WorkOrderItem.position)))
    versions: dict[uuid.UUID, dict] = {}
    cut_groups: dict[str, dict] = {}
    glass, accessories, drawings, issues = [], defaultdict(lambda: {"qty": Decimal(0)}), [], []

    for item in items:
        if item.formula_set_version_id not in versions:
            versions[item.formula_set_version_id] = db.get(FormulaSetVersion, item.formula_set_version_id).snapshot
        materials = versions[item.formula_set_version_id]["materials"]
        calc = item.calc
        ref = f"{item.position}" + (f" ({item.location})" if item.location else "")
        for issue in calc.get("issues", []):
            issues.append({**issue, "item": item.position})
        for p in calc.get("pieces", []):
            mat = materials.get(p["material_code"])
            sku = _sku(mat, p["material_code"], item.color_code)
            g = cut_groups.setdefault(sku, {
                "sku": sku, "material_code": p["material_code"], "material_name": p.get("material_name"),
                "unit": (mat or {}).get("unit", "m"), "bar_length_mm": (mat or {}).get("bar_length_mm"),
                "color": item.color_code, "pieces": defaultdict(lambda: {"qty": 0, "refs": []})})
            key = (p["length_mm"], p["angle_left"], p["angle_right"], p.get("label", p["key"]))
            entry = g["pieces"][key]
            entry["qty"] += int(p["qty"]) * item.qty
            entry["refs"].append(ref)
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
        drawings.append({"item": item.position, "location": item.location, "qty": item.qty,
                         "model_code": model.code if model else None, "model_name": model.name if model else None,
                         "model_image_id": str(model.image_id) if model and model.image_id else None,
                         "opening_width_mm": str(item.opening_width_mm), "opening_height_mm": str(item.opening_height_mm),
                         "width_mm": calc.get("inputs", {}).get("width_mm"),
                         "height_mm": calc.get("inputs", {}).get("height_mm"),
                         "elements": calc.get("drawing", [])})

    resolver = CostResolver(db)
    cut_list, optimisation, costs, missing = [], [], [], set()
    for sku, g in sorted(cut_groups.items()):
        # (group key is the SKU, so all its pieces share one colour)
        pieces = [{"length_mm": Decimal(k[0]), "angle_left": k[1], "angle_right": k[2], "label": k[3],
                   "qty": v["qty"], "refs": v["refs"]} for k, v in g["pieces"].items()]
        pieces.sort(key=lambda p: p["length_mm"], reverse=True)
        cut_list.append({"sku": sku, "material_code": g["material_code"], "material_name": g["material_name"],
                         "pieces": pieces, "total_pieces": sum(p["qty"] for p in pieces),
                         "total_length_mm": sum((p["length_mm"] * p["qty"] for p in pieces), Decimal(0))})
        cost, _, _ = resolver.resolve(g["material_code"], g["color"])
        if g["bar_length_mm"]:
            plan = optimise([{"length_mm": p["length_mm"], "qty": p["qty"], "label": p["label"],
                              "angle_left": p["angle_left"], "angle_right": p["angle_right"]} for p in pieces],
                            bar_length_mm=Decimal(g["bar_length_mm"]), kerf_mm=settings.saw_kerf_mm,
                            trim_mm=settings.bar_trim_mm, min_offcut_mm=settings.min_reusable_offcut_mm)
            plan["sku"] = sku
            for t in plan["too_long"]:
                issues.append({"level": "error", "code": "PIECE_LONGER_THAN_BAR", "message": f"{sku}: {t['length_mm']} mm",
                               "where": sku})
            optimisation.append(plan)
            consumed_m = plan["total_length_mm"] / 1000
        else:
            consumed_m = cut_list[-1]["total_length_mm"] / 1000
        if cost is None:
            missing.add(g["material_code"])
        else:
            costs.append({"type": "profile", "sku": sku, "qty": consumed_m, "unit": "m", "unit_cost": cost,
                          "amount": money(consumed_m * cost)})

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
        "waste_pct": (total_waste / total_bars_length * 100).quantize(Decimal("0.01")) if total_bars_length else Decimal(0),
        "glass": glass,
        "glass_area_by_type": dict(glass_summary),
        "accessories": acc_list,
        "costs": costs,
        "material_cost_total": money(sum((c["amount"] for c in costs), Decimal(0))),
        "missing_costs": sorted(missing),
        "drawings": drawings,
        "issues": issues,
        "settings": {"saw_kerf_mm": settings.saw_kerf_mm, "bar_trim_mm": settings.bar_trim_mm,
                     "min_reusable_offcut_mm": settings.min_reusable_offcut_mm},
    })
