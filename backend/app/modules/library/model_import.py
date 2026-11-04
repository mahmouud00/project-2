"""استيراد النماذج من إكسيل: a list of window/door models, created in each chosen profile system.

The first sheet that has a name column and a code column is read (headers in any order; extra columns ignored):

    الكود (or الرقم المرجعي) · الاسم (or اسم المنتج) · النوع (شباك / باب / شيش) · الوصف · الرسمة

`الرسمة` is optional: the model's drawing as JSON (a list of drawing elements: frame / sash / glass / panel / mullion
with x, y, w, h expressions and an opening). A model is created with its name, type and drawing only — no pieces,
glass, accessories or formulas: those (the deductions) are entered by the system's author in the model editor and
checked by the reference tests before publishing, as for any model. A code already in a system is skipped there
(never changed). Preview first; the import is all or nothing.
"""
from __future__ import annotations

import io
import json

from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import select

from app.core.audit import audit
from app.core.errors import ValidationFailed
from app.modules.library.models import ProductModel, ProfileSystem
from app.modules.library.schemas import Definition

NAME = ("الاسم", "اسم المنتج", "اسم النموذج")
CODE = ("الكود", "الرقم المرجعي", "كود النموذج")
CATEGORY = {"شباك": "window", "باب": "door", "شيش": "shutter", "شاتر": "shutter",
            "window": "window", "door": "door", "shutter": "shutter"}


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def read_models(data: bytes) -> tuple[list[dict], list[dict]]:
    """Rows {code, name, category, description, drawing} and errors {where, message}."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ValidationFailed("The file is not an Excel workbook (.xlsx)", code="BAD_EXCEL")
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        cols = [_text(h) for h in (next(it, None) or [])]
        name_i = next((cols.index(h) for h in NAME if h in cols), None)
        code_i = next((cols.index(h) for h in CODE if h in cols), None)
        if name_i is None or code_i is None:
            continue
        col = {h: cols.index(h) for h in ("النوع", "الوصف", "الرسمة") if h in cols}
        rows, errors, seen = [], [], set()
        for n, r in enumerate(it, start=2):
            get = lambda i: r[i] if i is not None and i < len(r) else None      # noqa: E731
            code, name = _text(get(code_i)), _text(get(name_i))
            if not code and not name:
                continue
            where = f"{ws.title} سطر {n}"
            if not code or not name:
                errors.append({"where": where, "message": "الكود والاسم مطلوبين"})
                continue
            if len(code) > 60:
                errors.append({"where": where, "message": "الكود أطول من 60 حرف"})
                continue
            if code in seen:
                errors.append({"where": where, "message": f"الكود {code} متكرر في الملف"})
                continue
            seen.add(code)
            kind = _text(get(col.get("النوع")))
            category = CATEGORY.get(kind, CATEGORY.get(kind.lower(), None)) if kind else "window"
            if category is None:
                errors.append({"where": where, "message": f"النوع مش معروف: {kind} (شباك أو باب أو شيش)"})
                continue
            drawing = []
            raw = _text(get(col.get("الرسمة")))
            if raw:
                try:
                    drawing = Definition(drawing=json.loads(raw)).model_dump(mode="json", exclude_none=True)["drawing"]
                except (ValueError, ValidationError):
                    errors.append({"where": where, "message": "الرسمة مش مكتوبة صح"})
                    continue
            rows.append({"code": code, "name": name, "category": category,
                         "description": _text(get(col.get("الوصف"))), "drawing": drawing})
        return rows, errors
    raise ValidationFailed("No sheet with a name and a code column", code="BAD_EXCEL")


def import_models(db, systems: list[ProfileSystem], data: bytes, apply: bool) -> dict:
    rows, errors = read_models(data)
    out = []
    for system in systems:
        existing = set(db.scalars(select(ProductModel.code).where(ProductModel.system_id == system.id,
                                                                  ProductModel.deleted_at.is_(None))))
        new = [r for r in rows if r["code"] not in existing]
        out.append({"id": str(system.id), "code": system.code, "name": system.name,
                    "new": len(new), "existing": len(rows) - len(new)})
        if not apply or errors:
            continue
        for i, r in enumerate(new):
            model = ProductModel(system_id=system.id, code=r["code"], name=r["name"], category=r["category"],
                                 description=r["description"], status="trial", is_active=True, sort=i,
                                 definition={"drawing": r["drawing"]} if r["drawing"] else {})
            db.add(model)
            db.flush()
            audit(db, model, "create")
    report = {"rows": len(rows), "systems": out, "models_new": sum(s["new"] for s in out),
              "errors": errors[:200], "error_count": len(errors)}
    if apply and errors:
        db.rollback()
        raise ValidationFailed("Some rows have errors: nothing was imported", code="IMPORT_ERRORS", details=report)
    return report
