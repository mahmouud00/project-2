"""Library update packages (offline distribution of the MYTech library).

Vendor side:   export (zip with package.json + media files)  ->  sign with
               `python -m tools.vendor_admin sign-package` (private key stays
               with the vendor).
Customer side: preview (verify signature + file hashes, compute what changes)
               -> apply (upsert library rows, insert new immutable versions).

Rows keep the vendor's ids, so the same system/material/model has the same
id at every customer. Company calibration/overrides/settings are tenant rows
and are never touched by an import.
"""
from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Uuid
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db.base import PLATFORM_COMPANY_ID
from app.licensing.signing import verify_document
from app.modules.library.models import (Color, FormulaSetVersion, Material, MaterialVariant, MediaFile,
                                        ModelTestCase, ProductModel, ProfileSystem, SystemConstant)

FORMAT = 1
_SKIP = {"company_id", "created_at", "updated_at", "created_by", "updated_by", "version"}


def _row(obj) -> dict:
    out = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
        if attr.key in _SKIP:
            continue
        v = getattr(obj, attr.key)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, Decimal):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        out[attr.key] = v
    return out


def _from_row(model, data: dict) -> dict:
    """Package JSON -> column values, converted by column type."""
    cols = {a.key: a.columns[0].type for a in sa_inspect(model).mapper.column_attrs}
    out = {}
    for k, v in data.items():
        if k not in cols or k in _SKIP:
            continue
        col_type = cols[k]
        if v is not None:
            if isinstance(col_type, Uuid):
                v = uuid.UUID(str(v))
            elif isinstance(col_type, Numeric):
                v = Decimal(str(v))
            elif isinstance(col_type, DateTime) and isinstance(v, str):
                v = datetime.fromisoformat(v)
        out[k] = v
    return out


# ---------------------------------------------------------------- export (vendor)
def export_package(db: Session, system_codes: list[str] | None = None, notes: str = "") -> bytes:
    stmt = select(ProfileSystem).where(ProfileSystem.company_id == PLATFORM_COMPANY_ID)
    if system_codes:
        stmt = stmt.where(ProfileSystem.code.in_(system_codes))
    systems = db.scalars(stmt.order_by(ProfileSystem.code)).all()
    media_ids: set[uuid.UUID] = set()
    out_systems = []
    for s in systems:
        if s.image_id:
            media_ids.add(s.image_id)
        materials = db.scalars(select(Material).where(Material.system_id == s.id)).all()
        models = db.scalars(select(ProductModel).where(ProductModel.system_id == s.id)).all()
        versions = db.scalars(select(FormulaSetVersion).where(FormulaSetVersion.system_id == s.id)
                              .order_by(FormulaSetVersion.version_no)).all()
        # shared library materials (system_id NULL) used by this system's models
        used = set()
        for v in versions:
            used |= set(v.snapshot.get("materials", {}))
        shared = db.scalars(select(Material).where(Material.company_id == PLATFORM_COMPANY_ID,
                                                   Material.system_id.is_(None), Material.code.in_(used))).all() if used else []
        mats = []
        for m in list(materials) + list(shared):
            if m.image_id:
                media_ids.add(m.image_id)
            mats.append({"row": _row(m), "variants": [_row(v) for v in db.scalars(
                select(MaterialVariant).where(MaterialVariant.material_id == m.id))]})
        mods = []
        for m in models:
            if m.image_id:
                media_ids.add(m.image_id)
            mods.append({"row": _row(m), "tests": [_row(t) for t in db.scalars(
                select(ModelTestCase).where(ModelTestCase.model_id == m.id))]})
        out_systems.append({
            "system": _row(s),
            "constants": [_row(c) for c in db.scalars(select(SystemConstant).where(SystemConstant.system_id == s.id))],
            "materials": mats, "models": mods, "versions": [_row(v) for v in versions],
        })
    media = db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))).all() if media_ids else []
    payload = {
        "format": FORMAT, "package_id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "colors": [_row(c) for c in db.scalars(select(Color).where(Color.company_id == PLATFORM_COMPANY_ID))],
        "media": [_row(m) for m in media], "systems": out_systems,
    }
    from app.modules.library.router import media_path

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.json", json.dumps({"payload": payload}, ensure_ascii=False))
        for m in media:
            z.write(media_path(m.sha256), f"media/{m.sha256}")
    return buf.getvalue()


def sign_package(data: bytes, private_key) -> bytes:
    from app.licensing.signing import sign_document

    src = zipfile.ZipFile(io.BytesIO(data))
    doc = json.loads(src.read("package.json"))
    signed = sign_document(private_key, doc["payload"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.json", json.dumps(signed, ensure_ascii=False))
        for name in src.namelist():
            if name != "package.json":
                z.writestr(name, src.read(name))
    return out.getvalue()


# ---------------------------------------------------------------- verify (customer)
MAX_PACKAGE_BYTES = 500 * 1024 * 1024


def open_package(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = json.loads(z.read("package.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise ValidationFailed("Not a library package", code="PACKAGE_INVALID")
    if not verify_document(doc):
        raise ValidationFailed("Package signature is not valid", code="PACKAGE_SIGNATURE_INVALID")
    payload = doc["payload"]
    if payload.get("format") != FORMAT:
        raise ValidationFailed("Unsupported package format", code="PACKAGE_FORMAT")
    for m in payload.get("media", []):
        try:
            blob = z.read(f"media/{m['sha256']}")
        except KeyError:
            raise ValidationFailed("Package is missing a file", code="PACKAGE_INCOMPLETE")
        if hashlib.sha256(blob).hexdigest() != m["sha256"]:
            raise ValidationFailed("Package file is corrupted", code="PACKAGE_CORRUPTED")
    for s in payload.get("systems", []):
        for v in s.get("versions", []):
            from app.modules.library.service import snapshot_hash
            if snapshot_hash(v["snapshot"]) != v["sha256"]:
                raise ValidationFailed("Package version data is corrupted", code="PACKAGE_CORRUPTED")
    return payload, z


def _changes(old: dict | None, new: dict, ignore=("id",)) -> dict:
    if old is None:
        return {}
    return {k: {"old": old.get(k), "new": v} for k, v in new.items()
            if k not in ignore and _norm(old.get(k)) != _norm(v)}


def _norm(v):
    if isinstance(v, str):
        try:
            return Decimal(v).normalize()
        except Exception:
            return v
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return Decimal(str(v)).normalize()
    return v


def compute_diff(db: Session, payload: dict) -> dict:
    """What applying the package would change, per system."""
    systems_out = []
    for s in payload["systems"]:
        srow = s["system"]
        existing = db.get(ProfileSystem, uuid.UUID(srow["id"]))
        entry = {"code": srow["code"], "name": srow["name"], "status": "new" if existing is None else "unchanged",
                 "system_changes": _changes(_row(existing) if existing else None, srow,
                                            ignore=("id", "current_version_id")),
                 "constants": {"added": [], "changed": [], "removed": []},
                 "materials": {"added": [], "changed": [], "removed": []},
                 "models": {"added": [], "changed": [], "removed": []},
                 "new_versions": []}
        old_consts = {c.name: c for c in db.scalars(select(SystemConstant).where(
            SystemConstant.system_id == uuid.UUID(srow["id"])))}
        for c in s["constants"]:
            old = old_consts.pop(c["name"], None)
            if old is None:
                entry["constants"]["added"].append({"name": c["name"], "value": c["value"]})
            elif _norm(str(old.value)) != _norm(c["value"]) or old.label != c["label"]:
                entry["constants"]["changed"].append({"name": c["name"], "old": str(old.value), "new": c["value"]})
        entry["constants"]["removed"] = sorted(old_consts)
        pkg_material_ids = set()
        for m in s["materials"]:
            row = m["row"]
            pkg_material_ids.add(row["id"])
            old = db.get(Material, uuid.UUID(row["id"]))
            if old is None:
                entry["materials"]["added"].append(row["code"])
            else:
                ch = _changes(_row(old), row)
                if ch:
                    entry["materials"]["changed"].append({"code": row["code"], "changes": ch})
        for old in db.scalars(select(Material).where(Material.system_id == uuid.UUID(srow["id"]), Material.is_active)):
            if str(old.id) not in pkg_material_ids:
                entry["materials"]["removed"].append(old.code)
        pkg_model_ids = set()
        for m in s["models"]:
            row = m["row"]
            pkg_model_ids.add(row["id"])
            old = db.get(ProductModel, uuid.UUID(row["id"]))
            if old is None:
                entry["models"]["added"].append(row["code"])
            else:
                ch = _changes(_row(old), row)
                if ch:
                    entry["models"]["changed"].append({"code": row["code"], "fields": sorted(ch)})
        for old in db.scalars(select(ProductModel).where(ProductModel.system_id == uuid.UUID(srow["id"]),
                                                         ProductModel.is_active)):
            if str(old.id) not in pkg_model_ids:
                entry["models"]["removed"].append(old.code)
        for v in s["versions"]:
            existing_v = db.get(FormulaSetVersion, uuid.UUID(v["id"]))
            if existing_v is None:
                entry["new_versions"].append(v["version_no"])
            elif existing_v.sha256 != v["sha256"]:
                raise ValidationFailed("Package rewrites a published version", code="PACKAGE_VERSION_CONFLICT",
                                       details={"system": srow["code"], "version_no": v["version_no"]})
        changed = (entry["system_changes"] or any(entry[k][x] for k in ("constants", "materials", "models")
                                                 for x in ("added", "changed", "removed")) or entry["new_versions"])
        if existing is not None and changed:
            entry["status"] = "changed"
        systems_out.append(entry)
    return {"package_id": payload["package_id"], "created_at": payload["created_at"], "notes": payload.get("notes", ""),
            "systems": systems_out}


# ---------------------------------------------------------------- apply (customer)
def _upsert(db: Session, model, data: dict):
    values = _from_row(model, data)
    obj = db.get(model, values["id"])
    if obj is None:
        obj = model(company_id=PLATFORM_COMPANY_ID, **values)
        db.add(obj)
    else:
        if obj.company_id != PLATFORM_COMPANY_ID:
            raise ValidationFailed("Package collides with company data", code="PACKAGE_COLLISION")
        for k, v in values.items():
            setattr(obj, k, v)
    return obj


def apply_package(db: Session, payload: dict, z: zipfile.ZipFile) -> None:
    """Runs on the system session inside the caller's transaction."""
    from app.modules.library.router import media_path
    from app.modules.org.service import ensure_platform_company

    ensure_platform_company(db)
    for m in payload.get("media", []):
        path = media_path(m["sha256"])
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read(f"media/{m['sha256']}"))
        if db.get(MediaFile, uuid.UUID(m["id"])) is None:
            db.add(MediaFile(company_id=PLATFORM_COMPANY_ID, **_from_row(MediaFile, m)))
    for c in payload.get("colors", []):
        _upsert(db, Color, c)
    db.flush()
    for s in payload["systems"]:
        srow = dict(s["system"])
        current_version_id = srow.pop("current_version_id", None)
        system = _upsert(db, ProfileSystem, srow)
        db.flush()
        keep = set()
        for c in s["constants"]:
            keep.add(c["name"])
            existing = db.scalar(select(SystemConstant).where(SystemConstant.system_id == system.id,
                                                              SystemConstant.name == c["name"]))
            if existing is not None and str(existing.id) != c["id"]:
                db.delete(existing)
                db.flush()
            _upsert(db, SystemConstant, c)
        for old in db.scalars(select(SystemConstant).where(SystemConstant.system_id == system.id)):
            if old.name not in keep:
                db.delete(old)
        pkg_materials = set()
        for m in s["materials"]:
            pkg_materials.add(m["row"]["id"])
            mat = _upsert(db, Material, m["row"])
            db.flush()
            pkg_variants = set()
            for v in m["variants"]:
                pkg_variants.add(v["id"])
                _upsert(db, MaterialVariant, v)
            for old in db.scalars(select(MaterialVariant).where(MaterialVariant.material_id == mat.id)):
                if str(old.id) not in pkg_variants:
                    old.is_active = False
        for old in db.scalars(select(Material).where(Material.system_id == system.id)):
            if str(old.id) not in pkg_materials:
                old.is_active = False  # never deleted: stock and orders reference it
        pkg_models = set()
        for m in s["models"]:
            pkg_models.add(m["row"]["id"])
            model = _upsert(db, ProductModel, m["row"])
            db.flush()
            pkg_tests = set()
            for t in m["tests"]:
                pkg_tests.add(t["id"])
                _upsert(db, ModelTestCase, t)
            for old in db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == model.id)):
                if str(old.id) not in pkg_tests:
                    db.delete(old)
        for old in db.scalars(select(ProductModel).where(ProductModel.system_id == system.id)):
            if str(old.id) not in pkg_models:
                old.is_active = False
        db.flush()
        for v in s["versions"]:
            if db.get(FormulaSetVersion, uuid.UUID(v["id"])) is None:
                db.add(FormulaSetVersion(company_id=PLATFORM_COMPANY_ID, **_from_row(FormulaSetVersion, v)))
        db.flush()
        system.current_version_id = uuid.UUID(current_version_id) if current_version_id else None


def pending_path(import_id: uuid.UUID):
    return get_settings().media_dir / "packages" / f"{import_id}.zip"
