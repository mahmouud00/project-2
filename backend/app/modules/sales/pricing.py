"""Cost and price of a calculated window/door.

Unit cost of a material for a company, first found wins:
  company setting for (material, colour) -> company setting for (material, all colours)
  -> library variant reference cost -> library material reference cost.
A company price is reduced by the supplier discount: the one set on the material (colour, then all colours), else
the company's discount for the material's profile system (settings `supplier_discounts`).
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.library.models import CompanyMaterialSetting, Material, MaterialVariant
from app.modules.library.service import find_material

TWO = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


class CostResolver:
    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[tuple[str, str], tuple[Decimal | None, str, Material | None]] = {}

    def _system_discount(self, system_id) -> Decimal | None:
        """The company's supplier discount for this profile system (company settings), if any."""
        from app.modules.library.models import ProfileSystem
        from app.modules.org.settings import get_company_settings

        if not hasattr(self, "_discounts"):
            from sqlalchemy import text
            company_id = self.db.scalar(text("SELECT NULLIF(current_setting('app.company_id', true), '')"))
            self._discounts = get_company_settings(self.db, uuid.UUID(company_id)).supplier_discounts if company_id else {}
        system = self.db.get(ProfileSystem, system_id)
        return self._discounts.get(system.code) if system else None

    def resolve(self, code: str, color: str | None) -> tuple[Decimal | None, str, Material | None]:
        """-> (unit cost, sku, material)"""
        key = (code, color or "")
        if key in self._cache:
            return self._cache[key]
        material = find_material(self.db, code)
        if material is None:
            self._cache[key] = (None, code, None)
            return self._cache[key]
        variant = None
        if color:
            variant = self.db.scalar(select(MaterialVariant).where(MaterialVariant.material_id == material.id,
                                                                   MaterialVariant.color_code == color))
        settings = {s.color_code: s for s in self.db.scalars(
            select(CompanyMaterialSetting).where(CompanyMaterialSetting.material_id == material.id))}
        cost = None
        discount = None
        for candidate in (settings.get(color or "\0"), settings.get("")):
            if candidate is not None and discount is None and candidate.discount_pct is not None:
                discount = candidate.discount_pct
            if candidate is not None and candidate.unit_cost is not None and cost is None:
                cost = candidate.unit_cost
        if cost is not None:
            if discount is None and material.system_id is not None:
                discount = self._system_discount(material.system_id)
            if discount:
                cost = (cost * (1 - Decimal(discount) / 100)).quantize(Decimal("0.0001"))
        if cost is None and variant is not None and variant.reference_cost is not None:
            cost = variant.reference_cost
        if cost is None:
            cost = material.reference_cost
        sku = variant.sku if variant is not None else material.code
        self._cache[key] = (cost, sku, material)
        return self._cache[key]


def cost_of_calc(resolver: CostResolver, calc: dict, color: str | None, glass_code: str | None,
                 waste_pct: Decimal = Decimal(0)) -> dict:
    """Estimated material cost of ONE unit (used for quotes)."""
    lines, missing = [], set()
    total = Decimal(0)
    factor = 1 + Decimal(waste_pct) / 100
    for p in calc.get("pieces", []):
        cost, sku, mat = resolver.resolve(p["material_code"], color)
        qty_m = Decimal(p["length_mm"]) / 1000 * int(p["qty"])
        if mat is not None and mat.unit != "m":
            qty_m = Decimal(int(p["qty"]))
        if cost is None:
            missing.add(p["material_code"])
            continue
        amount = qty_m * cost * (factor if mat is not None and mat.unit == "m" else 1)
        total += amount
        lines.append({"type": "profile", "sku": sku, "qty": str(qty_m), "unit_cost": str(cost), "amount": str(money(amount))})
    for g in calc.get("glass", []):
        code = g.get("material_code") or glass_code
        if not code:
            missing.add("(glass type not chosen)")
            continue
        cost, sku, _ = resolver.resolve(code, None)
        if cost is None:
            missing.add(code)
            continue
        amount = Decimal(g["area_m2"]) * cost
        total += amount
        lines.append({"type": "glass", "sku": sku, "qty": g["area_m2"], "unit_cost": str(cost), "amount": str(money(amount))})
    for a in calc.get("accessories", []):
        cost, sku, _ = resolver.resolve(a["material_code"], color)
        if cost is None:
            missing.add(a["material_code"])
            continue
        amount = Decimal(a["qty"]) * cost
        total += amount
        lines.append({"type": "accessory", "sku": sku, "qty": a["qty"], "unit_cost": str(cost), "amount": str(money(amount))})
    return {"total": money(total), "lines": lines, "missing_costs": sorted(missing)}


def unit_price(price_list, items: list, model_id, system_id, area_m2: Decimal, unit_cost: Decimal) -> Decimal:
    item = next((i for i in items if i.model_id == model_id), None) or \
        next((i for i in items if i.system_id == system_id and i.model_id is None), None)
    if item is not None and item.price_per_m2 is not None:
        price = area_m2 * item.price_per_m2
    else:
        margin = item.margin_pct if item is not None and item.margin_pct is not None else price_list.margin_pct
        price = (unit_cost + price_list.labor_cost_per_m2 * area_m2) * (1 + margin / 100)
    return money(max(price, price_list.min_unit_price))
