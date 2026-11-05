"""نسخ النماذج من قطاع لقطاع: a model with everything in it (name, type, description, picture, colour pictures,
variables, formulas, pieces with their deductions, glass, accessories, rules, drawing, reference tests) copied into
another system of the company's own.

When the other system already has the model (same name, spelled loosely: أ/إ/آ = ا, ة = ه, ى = ي, spaces; or the
same code), nothing of it is changed: only what it does not have yet is added — a variable, formula, piece, glass or
accessory whose key it lacks, a rule it lacks, colour pictures of colours it lacks, the picture / description / drawing
when empty, and the reference tests when it had no pieces yet (a model imported from Excel). Its own data always wins.

The deductions are copied exactly as written, never adapted: the two systems must use the same unit (a plain number
in a formula cannot be converted safely), the copied / merged model stays as it was (a new one is «تحت التجربة»), and
constants the formulas use that the other system lacks are reported, so the author adds them before publishing
(publishing re-runs every reference test, as always).
"""
from __future__ import annotations

import copy
import re

from sqlalchemy import select

from app.core.audit import audit, snapshot
from app.core.errors import ValidationFailed
from app.modules.library.models import ModelTestCase, ProductModel, ProfileSystem, SystemConstant

SECTIONS = {"params": "name", "formulas": "key", "pieces": "key", "glass": "key", "accessories": "key"}
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ـ": None})


def same_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").translate(_LETTERS)).strip().lower()


def _expressions(definition: dict) -> str:
    out = []
    for items in definition.values():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    out.extend(str(v) for v in item.values() if isinstance(v, str))
    return " ".join(out)


def _constants_missing(db, source: ProfileSystem, target: ProfileSystem, definition: dict) -> list[str]:
    names = set(db.scalars(select(SystemConstant.name).where(SystemConstant.system_id == source.id)))
    have = set(db.scalars(select(SystemConstant.name).where(SystemConstant.system_id == target.id)))
    text = _expressions(definition)
    return sorted(n for n in names - have if re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", text))


def _merge(target: ProductModel, source: ProductModel) -> tuple[dict, dict]:
    """(the target's new definition, what was added {section: count})."""
    mine = copy.deepcopy(target.definition or {})
    theirs = source.definition or {}
    added: dict[str, int] = {}
    for section, key in SECTIONS.items():
        have = {i.get(key) for i in mine.get(section, [])}
        new = [copy.deepcopy(i) for i in theirs.get(section, []) if i.get(key) not in have]
        if new:
            mine[section] = mine.get(section, []) + new
            added[section] = len(new)
    rules = {i.get("expr") for i in mine.get("validations", [])}
    new = [copy.deepcopy(i) for i in theirs.get("validations", []) if i.get("expr") not in rules]
    if new:
        mine["validations"] = mine.get("validations", []) + new
        added["validations"] = len(new)
    if not mine.get("drawing") and theirs.get("drawing"):
        mine["drawing"] = copy.deepcopy(theirs["drawing"])
        added["drawing"] = 1
    return mine, added


def copy_models(db, ctx, source: ProfileSystem, target: ProfileSystem, model_ids: list, apply: bool,
                copy_constants: bool = False) -> dict:
    if source.id == target.id:
        raise ValidationFailed("Choose another system to copy to", code="SAME_SYSTEM")
    if source.unit != target.unit:
        raise ValidationFailed("The two systems use different units", code="UNIT_MISMATCH",
                               details={"from": source.unit, "to": target.unit})
    models = db.scalars(select(ProductModel).where(ProductModel.system_id == source.id, ProductModel.id.in_(model_ids),
                                                   ProductModel.deleted_at.is_(None))
                        .order_by(ProductModel.sort, ProductModel.code)).all()
    if not models:
        raise ValidationFailed("Choose at least one model", code="NOTHING_SELECTED")
    existing = db.scalars(select(ProductModel).where(ProductModel.system_id == target.id,
                                                     ProductModel.deleted_at.is_(None))).all()
    by_name = {same_name(m.name): m for m in existing}
    by_code = {m.code: m for m in existing}
    next_sort = max((m.sort for m in existing), default=0) + 1
    rows = []
    for src in models:
        cases = db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == src.id)).all()
        match = by_name.get(same_name(src.name)) or by_code.get(src.code)
        row = {"id": str(src.id), "code": src.code, "name": src.name,
               "constants_missing": _constants_missing(db, source, target, src.definition or {})}
        if match is None:
            row.update(action="new", added={s: len((src.definition or {}).get(s, [])) for s in
                                            (*SECTIONS, "validations", "drawing") if (src.definition or {}).get(s)},
                       colors=len(src.color_images or {}), tests=len(cases))
            if apply:
                model = ProductModel(system_id=target.id, code=src.code, name=src.name, category=src.category,
                                     description=src.description, image_id=src.image_id,
                                     color_images=dict(src.color_images or {}), status="trial", is_active=True,
                                     sort=next_sort, definition=copy.deepcopy(src.definition or {}))
                next_sort += 1
                db.add(model)
                db.flush()
                audit(db, model, "create", note=f"نسخة من {source.code} / {src.code}")
                for c in cases:
                    _copy_case(db, model, c)
                by_code[model.code] = by_name[same_name(model.name)] = model
            rows.append(row)
            continue
        definition, added = _merge(match, src)
        colors = {k: v for k, v in (src.color_images or {}).items() if k not in (match.color_images or {})}
        fill = {}
        if not match.image_id and src.image_id:
            fill["image_id"] = src.image_id
        if not (match.description or "").strip() and (src.description or "").strip():
            fill["description"] = src.description
        had_pieces = bool((match.definition or {}).get("pieces"))
        mine_cases = db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == match.id)).all()
        names = {c.name for c in mine_cases}
        new_cases = [] if had_pieces else [c for c in cases if c.name not in names or not c.name]
        row.update(action="merge" if (added or colors or fill or new_cases) else "same", into_id=str(match.id),
                   into_code=match.code, into_name=match.name, added=added, colors=len(colors),
                   filled=sorted(fill), tests=len(new_cases), tests_skipped=len(cases) if had_pieces else 0)
        if apply and row["action"] == "merge":
            before = snapshot(match)
            match.definition = definition
            if colors:
                match.color_images = {**(match.color_images or {}), **colors}
            for k, v in fill.items():
                setattr(match, k, v)
            audit(db, match, "update", before, note=f"اتضافله من {source.code} / {src.code}")
            for c in new_cases:
                _copy_case(db, match, c)
        rows.append(row)
    missing = sorted({c for r in rows for c in r["constants_missing"]})
    copied_constants = []
    if copy_constants and missing:          # only when the author asks: the values are the source system's own
        for c in db.scalars(select(SystemConstant).where(SystemConstant.system_id == source.id,
                                                         SystemConstant.name.in_(missing))):
            copied_constants.append(c.name)
            if apply:
                new = SystemConstant(system_id=target.id, name=c.name, label=c.label, value=c.value, unit=c.unit,
                                     description=c.description, sort=c.sort)
                db.add(new)
                db.flush()
                audit(db, new, "create", note=f"نسخة من ثوابت {source.code}")
    return {"constants_copied": copied_constants, "from": {"id": str(source.id), "code": source.code, "name": source.name},
            "to": {"id": str(target.id), "code": target.code, "name": target.name},
            "models": rows, "new": sum(r["action"] == "new" for r in rows),
            "merged": sum(r["action"] == "merge" for r in rows), "same": sum(r["action"] == "same" for r in rows)}


def _copy_case(db, model: ProductModel, c: ModelTestCase) -> None:
    case = ModelTestCase(model_id=model.id, name=c.name, opening_width_mm=c.opening_width_mm,
                         opening_height_mm=c.opening_height_mm, params=copy.deepcopy(c.params or {}),
                         expected=copy.deepcopy(c.expected or {}))
    db.add(case)
    db.flush()
    audit(db, case, "create")
