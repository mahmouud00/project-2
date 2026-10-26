from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import PLATFORM_COMPANY_ID
from app.engine.compute import CalcError, Issue, calculate, check_definition
from app.licensing.service import entitlements
from app.licensing.signing import canonical
from app.modules.library.models import (CompanyCalibration, CompanyConstantOverride, FormulaSetVersion, Material,
                                        MaterialVariant, ModelTestCase, ProductModel, ProfileSystem, SystemConstant)
from app.tenancy.context import RequestContext

TOLERANCE_MM = Decimal("0.1")


# ---------------------------------------------------------------- access
def require_author(ctx: RequestContext) -> None:
    ctx.require("platform.library.author" if ctx.is_platform else "library.manage")


def require_deleter(ctx: RequestContext) -> None:
    if ctx.is_platform:
        ctx.require("platform.library.author")
    else:
        ctx.require("library.manage")
        ctx.require("library.delete")


def ensure_writable(ctx: RequestContext, obj) -> None:
    """Library rows belong to MYTech; a company may only edit its own private rows."""
    if obj.company_id != ctx.company_id:
        raise Forbidden("Library items are read-only; use calibration/overrides instead", code="LIBRARY_READ_ONLY")


def licensed_types(db: Session, ctx: RequestContext) -> set[str] | None:
    if ctx.is_platform:
        return None
    ent = entitlements(db, ctx.company_id)
    return {m.split(".", 1)[1] for m in ent.modules if m.startswith("mfg.")}


def visible_systems_stmt(db: Session, ctx: RequestContext):
    stmt = select(ProfileSystem)
    types = licensed_types(db, ctx)
    if types is not None:
        # own systems always; library systems only for licensed material types
        stmt = stmt.where(or_(ProfileSystem.company_id == ctx.company_id, ProfileSystem.material_type.in_(types)))
    return stmt


def get_system(db: Session, ctx: RequestContext, system_id: uuid.UUID) -> ProfileSystem:
    system = db.scalar(visible_systems_stmt(db, ctx).where(ProfileSystem.id == system_id))
    if system is None:
        raise NotFound("System not found")
    return system


def get_visible(db: Session, model, obj_id: uuid.UUID):
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFound(f"{model.__name__} not found")
    return obj


def find_material(db: Session, code: str) -> Material | None:
    """Own material first, then the library one with the same code."""
    rows = db.scalars(select(Material).where(Material.code == code)).all()
    for m in rows:
        if m.company_id != PLATFORM_COMPANY_ID:
            return m
    return rows[0] if rows else None


# ---------------------------------------------------------------- snapshot
def _material_entry(m: Material, variants: list[MaterialVariant]) -> dict:
    return {
        "id": str(m.id), "name": m.name, "kind": m.kind, "unit": m.unit, "category": m.category,
        "bar_length_mm": str(m.bar_length_mm) if m.bar_length_mm is not None else None,
        "min_piece_mm": str(m.min_piece_mm) if m.min_piece_mm is not None else None,
        "weight_kg_per_m": str(m.weight_kg_per_m) if m.weight_kg_per_m is not None else None,
        "variants": {v.color_code: v.sku for v in variants if v.is_active},
    }


def referenced_codes(definition: dict) -> set[str]:
    codes = set()
    for section in ("pieces", "accessories", "glass"):
        for item in definition.get(section, []):
            if item.get("material_code"):
                codes.add(item["material_code"])
    return codes


def build_snapshot(db: Session, system: ProfileSystem) -> dict:
    constants = db.scalars(select(SystemConstant).where(SystemConstant.system_id == system.id)
                           .order_by(SystemConstant.sort, SystemConstant.name)).all()
    models = db.scalars(select(ProductModel).where(ProductModel.system_id == system.id, ProductModel.is_active)
                        .order_by(ProductModel.sort, ProductModel.code)).all()
    materials: dict[str, Material] = {
        m.code: m for m in db.scalars(select(Material).where(Material.system_id == system.id, Material.is_active))}
    for model in models:
        for code in referenced_codes(model.definition) - set(materials):
            m = find_material(db, code)
            if m is not None and m.company_id in (system.company_id, PLATFORM_COMPANY_ID):
                materials[code] = m
    variants: dict[uuid.UUID, list[MaterialVariant]] = {}
    if materials:
        for v in db.scalars(select(MaterialVariant).where(
                MaterialVariant.material_id.in_([m.id for m in materials.values()]))):
            variants.setdefault(v.material_id, []).append(v)
    return {
        "format": 1,
        "system": {"id": str(system.id), "code": system.code, "name": system.name, "supplier": system.supplier,
                   "material_type": system.material_type, "unit": system.unit,
                   "rounding_step_mm": str(system.rounding_step_mm), "rounding_mode": system.rounding_mode,
                   "status": system.status},
        "constants": {c.name: {"value": str(c.value), "label": c.label, "unit": c.unit} for c in constants},
        "materials": {code: _material_entry(m, variants.get(m.id, [])) for code, m in sorted(materials.items())},
        "models": {m.code: {"id": str(m.id), "code": m.code, "name": m.name, "category": m.category,
                            "status": m.status, "image_id": str(m.image_id) if m.image_id else None,
                            **m.definition} for m in models},
    }


def model_snapshot(version_snapshot: dict, model_code: str) -> dict:
    model = version_snapshot["models"].get(model_code)
    if model is None:
        raise NotFound("Model not in this published version", code="MODEL_NOT_PUBLISHED")
    return {"system": version_snapshot["system"], "constants": version_snapshot["constants"],
            "materials": version_snapshot["materials"], "model": model}


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(canonical(snapshot)).hexdigest()


# ---------------------------------------------------------------- test cases
def run_test_case(snapshot: dict, case: ModelTestCase | dict) -> list[str]:
    get = (lambda k: case[k]) if isinstance(case, dict) else (lambda k: getattr(case, k))
    try:
        r = calculate(snapshot, opening_width_mm=get("opening_width_mm"), opening_height_mm=get("opening_height_mm"),
                      params=get("params") or {})
    except CalcError as e:
        return [str(e)]
    exp = get("expected") or {}
    failures = []

    def near(label, got, want):
        if got is None:
            failures.append(f"{label}: missing")
        elif abs(Decimal(str(got)) - Decimal(str(want))) > TOLERANCE_MM:
            failures.append(f"{label}: got {got} expected {want}")

    for k, want in exp.get("values", {}).items():
        near(f"value {k}", r.values.get(k), want)
    pieces = {p["key"]: p for p in r.pieces}
    for k, want in exp.get("pieces", {}).items():
        near(f"piece {k}", pieces.get(k, {}).get("length_mm"), want)
    for k, want in exp.get("piece_qty", {}).items():
        if pieces.get(k, {}).get("qty") != int(want):
            failures.append(f"piece {k} qty: got {pieces.get(k, {}).get('qty')} expected {want}")
    glass = {g["key"]: g for g in r.glass}
    for k, (w, h) in exp.get("glass", {}).items():
        near(f"glass {k} width", glass.get(k, {}).get("width_mm"), w)
        near(f"glass {k} height", glass.get(k, {}).get("height_mm"), h)
    acc = {a["key"]: a for a in r.accessories}
    for k, want in exp.get("accessories", {}).items():
        got = acc.get(k, {}).get("qty", Decimal(0))
        if Decimal(str(got)) != Decimal(str(want)):
            failures.append(f"accessory {k}: got {got} expected {want}")
    return failures


# ---------------------------------------------------------------- publish
def publish(db: Session, ctx: RequestContext, system: ProfileSystem, notes: str = "") -> FormulaSetVersion:
    ensure_writable(ctx, system)
    snapshot = build_snapshot(db, system)
    errors: dict[str, list[str]] = {}
    if not snapshot["models"]:
        raise ValidationFailed("System has no active models", code="NOTHING_TO_PUBLISH")
    for code in snapshot["models"]:
        model_snap = model_snapshot(snapshot, code)
        problems = check_definition(model_snap)
        if not problems:
            model_id = uuid.UUID(snapshot["models"][code]["id"])
            for case in db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == model_id)):
                problems += [f"test '{case.name}': {f}" for f in run_test_case(model_snap, case)]
        if problems:
            errors[code] = problems
    if errors:
        raise ValidationFailed("System cannot be published", code="PUBLISH_FAILED", details=errors)
    digest = snapshot_hash(snapshot)
    if system.current_version_id:
        current = db.get(FormulaSetVersion, system.current_version_id)
        if current is not None and current.sha256 == digest:
            return current
    last = db.scalar(select(func.max(FormulaSetVersion.version_no)).where(FormulaSetVersion.system_id == system.id))
    version = FormulaSetVersion(company_id=system.company_id, system_id=system.id, version_no=(last or 0) + 1,
                                snapshot=snapshot, sha256=digest, notes=notes)
    db.add(version)
    db.flush()
    system.current_version_id = version.id
    return version


# ---------------------------------------------------------------- calculation
def company_adjustments(db: Session, system_id: uuid.UUID) -> tuple[dict, dict]:
    cal = {c.constant_name: c.delta for c in db.scalars(
        select(CompanyCalibration).where(CompanyCalibration.system_id == system_id))}
    ovr = {o.constant_name: o.value for o in db.scalars(
        select(CompanyConstantOverride).where(CompanyConstantOverride.system_id == system_id))}
    return cal, ovr


def calculate_model(db: Session, ctx: RequestContext, model_id: uuid.UUID, *, opening_width_mm, opening_height_mm,
                    params: dict | None = None, version_id: uuid.UUID | None = None) -> dict:
    model = get_visible(db, ProductModel, model_id)
    system = get_system(db, ctx, model.system_id)
    if not ctx.is_platform:
        from app.licensing.service import require_module
        require_module(db, ctx.company_id, f"mfg.{system.material_type}")
    vid = version_id or system.current_version_id
    if vid is None:
        raise Conflict("System has no published version", code="NOT_PUBLISHED")
    version = db.get(FormulaSetVersion, vid)
    if version is None or version.system_id != system.id:
        raise NotFound("Version not found")
    snap = model_snapshot(version.snapshot, model.code)
    calibration, overrides = company_adjustments(db, system.id)
    try:
        result = calculate(snap, opening_width_mm=opening_width_mm, opening_height_mm=opening_height_mm,
                           params=params or {}, calibration=calibration, overrides=overrides)
    except CalcError as e:
        raise ValidationFailed(str(e), code=e.code, details=e.as_dict())
    if version.snapshot["system"].get("status") == "trial" or snap["model"].get("status") == "trial":
        result.issues.append(Issue("warning", "TRIAL_STATUS", "System or model is still under trial"))
    out = result.as_dict()
    out["meta"] = {
        "model_id": str(model.id), "model_code": model.code, "system_id": str(system.id),
        "formula_set_version_id": str(version.id), "version_no": version.version_no,
        "calibration": {k: str(v) for k, v in calibration.items()},
        "overrides": {k: str(v) for k, v in overrides.items()},
    }
    return out


def model_image(model, color_code: str | None):
    """The model's picture in this colour when there is one, else its main picture."""
    if model is None:
        return None
    by_color = model.color_images or {}
    chosen = by_color.get(color_code) if color_code else None
    return uuid.UUID(chosen) if chosen else model.image_id
