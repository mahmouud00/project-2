from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.common import Page, PageParams, paginate
from app.core.audit import apply_changes, audit, check_version, snapshot
from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.db.base import PLATFORM_COMPANY_ID
from app.engine.compute import CalcError, calculate, check_definition
from app.modules.library import schemas as S
from app.modules.library import service as svc
from app.modules.library.models import (Color, CompanyCalibration, CompanyConstantOverride, CompanyMaterialSetting,
                                        FormulaSetVersion, Material, MaterialVariant, MediaFile, ModelTestCase,
                                        ProductModel, ProfileSystem, SystemConstant)
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(tags=["library"])

ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAGIC = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"RIFF": "image/webp"}


def media_path(sha256: str):
    return get_settings().media_dir / sha256[:2] / sha256


# ---------------------------------------------------------------- media
def store_media(db, data: bytes, filename: str, mime: str, company_id: uuid.UUID | None = None) -> MediaFile:
    sha = hashlib.sha256(data).hexdigest()
    path = media_path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    kwargs = {"company_id": company_id} if company_id else {}
    media = MediaFile(sha256=sha, mime=mime, filename=filename[:255], size=len(data), **kwargs)
    db.add(media)
    db.flush()
    return media


def _media_out(m: MediaFile) -> S.MediaOut:
    out = S.MediaOut.model_validate(m)
    out.url = f"/api/v1/media/{m.id}"
    return out


@router.post("/library/media", response_model=S.MediaOut, status_code=201)
async def upload_media(file: UploadFile, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValidationFailed("Image larger than 5 MB", code="FILE_TOO_LARGE")
    mime = next((t for magic, t in _MAGIC.items() if data.startswith(magic)), None)
    if mime is None or (mime == "image/webp" and data[8:12] != b"WEBP"):
        raise ValidationFailed("Only PNG, JPEG or WEBP images", code="FILE_TYPE")
    media = store_media(db, data, file.filename or "image", mime)
    db.commit()
    return _media_out(media)


@router.get("/media/{media_id}")
def get_media(media_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, _ = dc
    media = db.get(MediaFile, media_id)
    if media is None or not media_path(media.sha256).exists():
        raise NotFound("File not found")
    return FileResponse(media_path(media.sha256), media_type=media.mime,
                        headers={"Cache-Control": "private, max-age=86400"})


# ---------------------------------------------------------------- colours
@router.get("/library/colors", response_model=list[S.ColorOut])
def list_colors(dc=Depends(require("library.read"))):
    db, _ = dc
    return db.scalars(select(Color).order_by(Color.code)).all()


@router.post("/library/colors", response_model=S.ColorOut, status_code=201)
def create_color(body: S.ColorIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    if db.scalar(select(Color).where(Color.code == body.code, Color.company_id == ctx.company_id)):
        raise Conflict("Colour code exists", code="DUPLICATE_CODE")
    color = Color(**body.model_dump())
    db.add(color)
    db.flush()
    audit(db, color, "create")
    db.commit()
    return color


@router.patch("/library/colors/{color_id}", response_model=S.ColorOut)
def update_color(color_id: uuid.UUID, body: S.ColorUpdate, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    color = svc.get_visible(db, Color, color_id)
    svc.ensure_writable(ctx, color)
    check_version(color, body.version)
    before = snapshot(color)
    apply_changes(color, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, color, "update", before)
    db.commit()
    return color


# ---------------------------------------------------------------- systems
def _system_out(s: ProfileSystem) -> S.SystemOut:
    out = S.SystemOut.model_validate(s)
    out.is_library = s.company_id == PLATFORM_COMPANY_ID
    return out


@router.get("/library/systems", response_model=list[S.SystemOut])
def list_systems(material_type: str | None = None, include_inactive: bool = False,
                 dc=Depends(require("library.read"))):
    db, ctx = dc
    stmt = svc.visible_systems_stmt(db, ctx).order_by(ProfileSystem.material_type, ProfileSystem.code)
    if material_type:
        stmt = stmt.where(ProfileSystem.material_type == material_type)
    if not include_inactive:
        stmt = stmt.where(ProfileSystem.is_active)
    return [_system_out(s) for s in db.scalars(stmt)]


@router.post("/library/systems", response_model=S.SystemOut, status_code=201)
def create_system(body: S.SystemIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    if db.scalar(select(ProfileSystem).where(ProfileSystem.code == body.code,
                                             ProfileSystem.company_id == ctx.company_id)):
        raise Conflict("System code exists", code="DUPLICATE_CODE")
    system = ProfileSystem(**body.model_dump())
    db.add(system)
    db.flush()
    # every system needs the two clearance constants (opening -> manufacturing size)
    for name, label in (("install_clearance_width", "خلوص التركيب في العرض"),
                        ("install_clearance_height", "خلوص التركيب في الارتفاع")):
        db.add(SystemConstant(system_id=system.id, name=name, label=label, value=Decimal(0), sort=-1))
    audit(db, system, "create")
    db.commit()
    return _system_out(system)


@router.get("/library/systems/{system_id}", response_model=S.SystemOut)
def get_system(system_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    return _system_out(svc.get_system(db, ctx, system_id))


@router.patch("/library/systems/{system_id}", response_model=S.SystemOut)
def update_system(system_id: uuid.UUID, body: S.SystemUpdate, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    system = svc.get_system(db, ctx, system_id)
    svc.ensure_writable(ctx, system)
    check_version(system, body.version)
    before = snapshot(system)
    apply_changes(system, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, system, "update", before)
    db.commit()
    return _system_out(system)


@router.get("/library/systems/{system_id}/constants", response_model=list[S.ConstantOut])
def list_constants(system_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    svc.get_system(db, ctx, system_id)
    return db.scalars(select(SystemConstant).where(SystemConstant.system_id == system_id)
                      .order_by(SystemConstant.sort, SystemConstant.name)).all()


@router.post("/library/systems/{system_id}/constants", response_model=S.ConstantOut, status_code=201)
def create_constant(system_id: uuid.UUID, body: S.ConstantIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    system = svc.get_system(db, ctx, system_id)
    svc.ensure_writable(ctx, system)
    if db.scalar(select(SystemConstant).where(SystemConstant.system_id == system_id,
                                              SystemConstant.name == body.name)):
        raise Conflict("Constant exists", code="DUPLICATE_NAME")
    const = SystemConstant(system_id=system_id, **body.model_dump())
    db.add(const)
    db.flush()
    audit(db, const, "create")
    db.commit()
    return const


@router.patch("/library/constants/{constant_id}", response_model=S.ConstantOut)
def update_constant(constant_id: uuid.UUID, body: S.ConstantUpdate, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    const = svc.get_visible(db, SystemConstant, constant_id)
    svc.ensure_writable(ctx, const)
    check_version(const, body.version)
    before = snapshot(const)
    apply_changes(const, body.model_dump(exclude_unset=True, exclude={"version"}))
    audit(db, const, "update", before)
    db.commit()
    return const


@router.delete("/library/constants/{constant_id}", status_code=204)
def delete_constant(constant_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    const = svc.get_visible(db, SystemConstant, constant_id)
    svc.ensure_writable(ctx, const)
    if const.name in ("install_clearance_width", "install_clearance_height"):
        raise ValidationFailed("Clearance constants are required", code="CONSTANT_REQUIRED")
    before = snapshot(const)
    db.delete(const)
    audit(db, const, "delete", before)
    db.commit()


# ---------------------------------------------------------------- materials
def _material_out(db, m: Material) -> S.MaterialOut:
    out = S.MaterialOut.model_validate(m)
    out.variants = [S.VariantOut.model_validate(v) for v in db.scalars(
        select(MaterialVariant).where(MaterialVariant.material_id == m.id).order_by(MaterialVariant.color_code))]
    return out


def _set_variants(db, material: Material, variants: list[S.VariantIn]) -> None:
    existing = {v.color_code: v for v in db.scalars(select(MaterialVariant)
                                                    .where(MaterialVariant.material_id == material.id))}
    wanted = {v.color_code for v in variants}
    for v in variants:
        row = existing.get(v.color_code)
        if row is None:
            db.add(MaterialVariant(material_id=material.id, **v.model_dump()))
        else:
            apply_changes(row, v.model_dump())
    for code, row in existing.items():
        if code not in wanted:
            row.is_active = False  # never delete: stock and orders may reference the SKU


@router.get("/library/materials", response_model=Page[S.MaterialOut])
def list_materials(system_id: uuid.UUID | None = None, kind: str | None = None, q: str | None = None,
                   params: PageParams = Depends(), dc=Depends(require("library.read"))):
    db, ctx = dc
    stmt = select(Material).order_by(Material.code)
    if system_id:
        svc.get_system(db, ctx, system_id)
        stmt = stmt.where(Material.system_id == system_id)
    if kind:
        stmt = stmt.where(Material.kind == kind)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Material.code.ilike(like), Material.name.ilike(like)))
    page = paginate(db, stmt, params, S.MaterialOut)
    page["items"] = [_material_out(db, db.get(Material, m.id)) for m in page["items"]]
    return page


@router.post("/library/materials", response_model=S.MaterialOut, status_code=201)
def create_material(body: S.MaterialIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    if body.system_id:
        svc.ensure_writable(ctx, svc.get_system(db, ctx, body.system_id))
    if db.scalar(select(Material).where(Material.code == body.code, Material.company_id == ctx.company_id)):
        raise Conflict("Material code exists", code="DUPLICATE_CODE")
    material = Material(**body.model_dump(exclude={"variants"}))
    db.add(material)
    db.flush()
    _set_variants(db, material, body.variants)
    audit(db, material, "create")
    db.commit()
    return _material_out(db, material)


@router.get("/library/materials/{material_id}", response_model=S.MaterialOut)
def get_material(material_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, _ = dc
    return _material_out(db, svc.get_visible(db, Material, material_id))


@router.patch("/library/materials/{material_id}", response_model=S.MaterialOut)
def update_material(material_id: uuid.UUID, body: S.MaterialUpdate, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    material = svc.get_visible(db, Material, material_id)
    svc.ensure_writable(ctx, material)
    check_version(material, body.version)
    before = snapshot(material)
    apply_changes(material, body.model_dump(exclude_unset=True, exclude={"version", "variants"}))
    if body.variants is not None:
        _set_variants(db, material, body.variants)
        material.updated_by = ctx.user_id
    audit(db, material, "update", before)
    db.commit()
    return _material_out(db, material)


@router.put("/library/materials/{material_id}/settings", status_code=204)
def set_material_settings(material_id: uuid.UUID, body: S.MaterialSettingIn, dc=Depends(require("library.manage"))):
    """Company's own price / internal code / visibility. Never touches the library row."""
    db, _ = dc
    svc.get_visible(db, Material, material_id)
    row = db.scalar(select(CompanyMaterialSetting).where(CompanyMaterialSetting.material_id == material_id,
                                                         CompanyMaterialSetting.color_code == body.color_code))
    if row is None:
        db.add(CompanyMaterialSetting(material_id=material_id, **body.model_dump()))
    else:
        apply_changes(row, body.model_dump())
    db.commit()


# ---------------------------------------------------------------- models
def _check_materials_exist(db, definition: S.Definition) -> None:
    missing = sorted(c for c in svc.referenced_codes(definition.model_dump()) if svc.find_material(db, c) is None)
    if missing:
        raise ValidationFailed("Unknown material codes", code="UNKNOWN_MATERIAL", details=missing)


@router.get("/library/models", response_model=list[S.ModelOut])
def list_models(system_id: uuid.UUID, include_inactive: bool = False, dc=Depends(require("library.read"))):
    db, ctx = dc
    svc.get_system(db, ctx, system_id)
    stmt = select(ProductModel).where(ProductModel.system_id == system_id).order_by(ProductModel.sort, ProductModel.code)
    if not include_inactive:
        stmt = stmt.where(ProductModel.is_active)
    return db.scalars(stmt).all()


@router.post("/library/models", response_model=S.ModelOut, status_code=201)
def create_model(body: S.ModelIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    system = svc.get_system(db, ctx, body.system_id)
    svc.ensure_writable(ctx, system)
    if db.scalar(select(ProductModel).where(ProductModel.system_id == system.id, ProductModel.code == body.code)):
        raise Conflict("Model code exists", code="DUPLICATE_CODE")
    _check_materials_exist(db, body.definition)
    model = ProductModel(**body.model_dump(exclude={"definition"}),
                         definition=body.definition.model_dump(mode="json", exclude_none=True))
    db.add(model)
    db.flush()
    audit(db, model, "create")
    db.commit()
    return model


@router.get("/library/models/{model_id}", response_model=S.ModelOut)
def get_model(model_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    model = svc.get_visible(db, ProductModel, model_id)
    svc.get_system(db, ctx, model.system_id)
    return model


@router.patch("/library/models/{model_id}", response_model=S.ModelOut)
def update_model(model_id: uuid.UUID, body: S.ModelUpdate, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    model = svc.get_visible(db, ProductModel, model_id)
    svc.ensure_writable(ctx, model)
    check_version(model, body.version)
    before = snapshot(model)
    data = body.model_dump(exclude_unset=True, exclude={"version", "definition"})
    apply_changes(model, data)
    if body.definition is not None:
        _check_materials_exist(db, body.definition)
        model.definition = body.definition.model_dump(mode="json", exclude_none=True)
    audit(db, model, "update", before)
    db.commit()
    return model


def _draft_snapshot(db, ctx, model: ProductModel) -> dict:
    system = svc.get_system(db, ctx, model.system_id)
    full = svc.build_snapshot(db, system)
    full["models"][model.code] = {"id": str(model.id), "code": model.code, "name": model.name,
                                  "category": model.category, "status": model.status, **model.definition}
    for code in svc.referenced_codes(model.definition) - set(full["materials"]):
        m = svc.find_material(db, code)
        if m is not None:
            full["materials"][code] = svc._material_entry(m, [])
    return svc.model_snapshot(full, model.code)


@router.post("/library/models/{model_id}/check")
def check_model(model_id: uuid.UUID, dc=Depends(require("library.read"))):
    """Static check of the draft definition (names, cycles, materials, syntax)."""
    db, ctx = dc
    model = svc.get_visible(db, ProductModel, model_id)
    return {"errors": check_definition(_draft_snapshot(db, ctx, model))}


@router.post("/library/models/{model_id}/preview")
def preview_model(model_id: uuid.UUID, body: S.CalculateIn, dc=Depends(get_db_and_ctx)):
    """Calculate with the unpublished draft (authors only) to try formulas before publishing."""
    db, ctx = dc
    svc.require_author(ctx)
    model = svc.get_visible(db, ProductModel, model_id)
    calibration, overrides = svc.company_adjustments(db, model.system_id)
    try:
        r = calculate(_draft_snapshot(db, ctx, model), opening_width_mm=body.opening_width_mm,
                      opening_height_mm=body.opening_height_mm, params=body.params,
                      calibration=calibration, overrides=overrides)
    except CalcError as e:
        raise ValidationFailed(str(e), code=e.code, details=e.as_dict())
    return r.as_dict()


@router.get("/library/models/{model_id}/tests", response_model=list[S.TestCaseOut])
def list_tests(model_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, _ = dc
    svc.get_visible(db, ProductModel, model_id)
    return db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == model_id)).all()


@router.post("/library/models/{model_id}/tests", response_model=S.TestCaseOut, status_code=201)
def create_test(model_id: uuid.UUID, body: S.TestCaseIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    model = svc.get_visible(db, ProductModel, model_id)
    svc.ensure_writable(ctx, model)
    case = ModelTestCase(model_id=model_id, **body.model_dump(mode="json"))
    db.add(case)
    db.flush()
    audit(db, case, "create")
    db.commit()
    return case


@router.delete("/library/tests/{test_id}", status_code=204)
def delete_test(test_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    case = svc.get_visible(db, ModelTestCase, test_id)
    svc.ensure_writable(ctx, case)
    before = snapshot(case)
    db.delete(case)
    audit(db, case, "delete", before)
    db.commit()


@router.post("/library/models/{model_id}/tests/run")
def run_tests(model_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    model = svc.get_visible(db, ProductModel, model_id)
    snap = _draft_snapshot(db, ctx, model)
    results = []
    for case in db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == model_id)):
        failures = svc.run_test_case(snap, case)
        results.append({"id": str(case.id), "name": case.name, "passed": not failures, "failures": failures})
    return {"passed": all(r["passed"] for r in results), "results": results}


# ---------------------------------------------------------------- publish / versions
@router.post("/library/systems/{system_id}/publish", response_model=S.VersionOut)
def publish_system(system_id: uuid.UUID, body: S.PublishIn, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    svc.require_author(ctx)
    system = svc.get_system(db, ctx, system_id)
    version = svc.publish(db, ctx, system, body.notes)
    audit(db, system, "update", None, note=f"published version {version.version_no}")
    db.commit()
    return version


@router.get("/library/systems/{system_id}/versions", response_model=list[S.VersionOut])
def list_versions(system_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    svc.get_system(db, ctx, system_id)
    return db.scalars(select(FormulaSetVersion).where(FormulaSetVersion.system_id == system_id)
                      .order_by(FormulaSetVersion.version_no.desc())).all()


@router.get("/library/versions/{version_id}")
def get_version(version_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    version = svc.get_visible(db, FormulaSetVersion, version_id)
    svc.get_system(db, ctx, version.system_id)
    return {"id": str(version.id), "version_no": version.version_no, "sha256": version.sha256,
            "published_at": version.published_at.isoformat(), "notes": version.notes, "snapshot": version.snapshot}


# ---------------------------------------------------------------- company adjustments
@router.get("/library/systems/{system_id}/adjustments", response_model=S.SystemAdjustments)
def get_adjustments(system_id: uuid.UUID, dc=Depends(require("library.read"))):
    db, ctx = dc
    svc.get_system(db, ctx, system_id)
    cal = db.scalars(select(CompanyCalibration).where(CompanyCalibration.system_id == system_id)).all()
    ovr = db.scalars(select(CompanyConstantOverride).where(CompanyConstantOverride.system_id == system_id)).all()
    return {"calibrations": [{"constant_name": c.constant_name, "delta": c.delta, "note": c.note} for c in cal],
            "overrides": [{"constant_name": o.constant_name, "value": o.value, "note": o.note} for o in ovr]}


@router.put("/library/systems/{system_id}/adjustments", response_model=S.SystemAdjustments)
def set_adjustments(system_id: uuid.UUID, body: S.SystemAdjustments, dc=Depends(require("library.manage"))):
    """Replace this company's calibration deltas / constant overrides for a system.
    Stored apart from the library: library updates never change them."""
    db, ctx = dc
    svc.get_system(db, ctx, system_id)
    names = set(db.scalars(select(SystemConstant.name).where(SystemConstant.system_id == system_id)))
    unknown = sorted({c.constant_name for c in body.calibrations + body.overrides} - names)  # type: ignore[operator]
    if unknown:
        raise ValidationFailed("Unknown constants", code="UNKNOWN_CONSTANT", details=unknown)
    for model, items, field in ((CompanyCalibration, body.calibrations, "delta"),
                                (CompanyConstantOverride, body.overrides, "value")):
        existing = {r.constant_name: r for r in db.scalars(select(model).where(model.system_id == system_id))}
        wanted = {i.constant_name for i in items}
        for item in items:
            row = existing.get(item.constant_name)
            before = snapshot(row) if row else None
            if row is None:
                row = model(system_id=system_id, constant_name=item.constant_name, note=item.note,
                            **{field: getattr(item, field)})
                db.add(row)
                db.flush()
                audit(db, row, "create")
            else:
                setattr(row, field, getattr(item, field))
                row.note = item.note
                db.flush()
                audit(db, row, "update", before)
        for name, row in existing.items():
            if name not in wanted:
                before = snapshot(row)
                db.delete(row)
                audit(db, row, "delete", before)
    db.commit()
    return get_adjustments(system_id, dc)


# ---------------------------------------------------------------- calculation
@router.post("/engine/calculate")
def calculate_endpoint(body: S.CalculateIn, dc=Depends(require("engine.calculate"))):
    db, ctx = dc
    return svc.calculate_model(db, ctx, body.model_id, opening_width_mm=body.opening_width_mm,
                               opening_height_mm=body.opening_height_mm, params=body.params,
                               version_id=body.version_id)


# ---------------------------------------------------------------- packages
class ExportIn(BaseModel):
    system_codes: list[str] = []
    notes: str = ""


@router.post("/library/packages/export")
def export_library_package(body: ExportIn, dc=Depends(get_db_and_ctx)):
    """Vendor: unsigned package of the platform library. Sign it with
    `python -m tools.vendor_admin sign-package` before sending to customers."""
    from app.modules.library.packages import export_package

    db, ctx = dc
    if not ctx.is_platform:
        raise Forbidden("Only MYTech can export the library", code="PLATFORM_ONLY")
    ctx.require("platform.library.author")
    data = export_package(db, body.system_codes or None, body.notes)
    name = f"mytech-library-{datetime.now(timezone.utc):%Y%m%d-%H%M}.unsigned.zip"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _check_can_import(ctx) -> None:
    ctx.require("library.import")
    if get_settings().is_online and not ctx.is_platform:
        # online: the library is shared by every company, only MYTech updates it
        raise Forbidden("Library updates are managed by MYTech", code="PLATFORM_ONLY")


@router.post("/library/packages/preview")
async def preview_library_package(file: UploadFile, dc=Depends(get_db_and_ctx)):
    """Verify a signed package and show exactly what it would change. Nothing is applied."""
    from app.modules.library.packages import MAX_PACKAGE_BYTES, compute_diff, open_package, pending_path
    from app.modules.library.models import LibraryImport

    db, ctx = dc
    _check_can_import(ctx)
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    if len(data) > MAX_PACKAGE_BYTES:
        raise ValidationFailed("Package too large", code="FILE_TOO_LARGE")
    payload, _ = open_package(data)
    diff = compute_diff(db, payload)
    record = LibraryImport(package_id=payload["package_id"], package_created_at=payload["created_at"],
                           status="previewed", summary=diff)
    db.add(record)
    db.flush()
    path = pending_path(record.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    db.commit()
    return {"import_id": str(record.id), "diff": diff}


@router.post("/library/packages/{import_id}/apply")
def apply_library_package(import_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    from app.db.session import system_session
    from app.modules.library.models import LibraryImport
    from app.modules.library.packages import apply_package, open_package, pending_path

    db, ctx = dc
    _check_can_import(ctx)
    record = db.get(LibraryImport, import_id)
    if record is None:
        raise NotFound("Import not found")
    if record.status != "previewed":
        raise Conflict("Import already processed", code="IMPORT_DONE")
    path = pending_path(record.id)
    if not path.exists():
        raise NotFound("Package file missing; preview again", code="PACKAGE_MISSING")
    payload, z = open_package(path.read_bytes())
    with system_session() as sys_db:  # writes platform rows: verified vendor package only
        apply_package(sys_db, payload, z)
        sys_db.commit()
    record.status = "applied"
    record.applied_at = datetime.now(timezone.utc)
    audit(db, record, "update", None, note=f"library package {record.package_id} applied")
    db.commit()
    path.unlink(missing_ok=True)
    return {"status": "applied", "import_id": str(record.id), "summary": record.summary}


@router.get("/library/packages/imports")
def list_imports(dc=Depends(require("library.import"))):
    from app.modules.library.models import LibraryImport

    db, _ = dc
    rows = db.scalars(select(LibraryImport).order_by(LibraryImport.created_at.desc())).all()
    return [{"id": str(r.id), "package_id": r.package_id, "package_created_at": r.package_created_at,
             "status": r.status, "created_at": r.created_at.isoformat(),
             "applied_at": r.applied_at.isoformat() if r.applied_at else None} for r in rows]
