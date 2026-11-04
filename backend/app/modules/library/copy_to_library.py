"""Copy a company's own profile systems into the MYTech (platform) library.

Used by the MYTech developer account: systems entered under a customer company
(company_id = that company) are copied — with their constants, materials (and
colour variants), models, test cases and images — into the platform library
(company_id = PLATFORM_COMPANY_ID) as fresh, unpublished rows. The developer
then reviews and publishes them, and exports a signed update package.

Runs on the *system* session (BYPASSRLS): it must read a customer company's
private rows and write platform rows, which no tenant session can do. New ids
are minted for every copied row; model definitions reference materials by
*code* (not id), so nothing inside them needs rewriting. Published versions are
not copied — the copy lands unpublished so the developer publishes it fresh.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.db.base import PLATFORM_COMPANY_ID
from app.modules.library.models import (Color, Material, MaterialVariant, MediaFile, ModelTestCase,
                                         ProductModel, ProfileSystem, SystemConstant)
from app.modules.library.service import referenced_codes
from app.modules.org.models import Company


# ---------------------------------------------------------------- sources (what can be copied)
def list_source_systems(sys_db: Session) -> list[dict]:
    """Every customer company (not the platform) with its own, non-deleted systems."""
    out = []
    companies = sys_db.scalars(select(Company).where(Company.id != PLATFORM_COMPANY_ID, Company.is_active)
                               .order_by(Company.name)).all()
    lib_codes = set(sys_db.scalars(select(ProfileSystem.code).where(
        ProfileSystem.company_id == PLATFORM_COMPANY_ID, ProfileSystem.deleted_at.is_(None))))
    for c in companies:
        systems = sys_db.scalars(select(ProfileSystem).where(
            ProfileSystem.company_id == c.id, ProfileSystem.deleted_at.is_(None))
            .order_by(ProfileSystem.material_type, ProfileSystem.code)).all()
        if not systems:
            continue
        out.append({
            "company_id": str(c.id), "company_code": c.code, "company_name": c.name,
            "systems": [{
                "id": str(s.id), "code": s.code, "name": s.name, "material_type": s.material_type,
                "models_count": sys_db.scalar(select(func.count(ProductModel.id)).where(
                    ProductModel.system_id == s.id, ProductModel.deleted_at.is_(None))) or 0,
                "already_in_library": s.code in lib_codes,
            } for s in systems],
        })
    return out


# ---------------------------------------------------------------- copy
class _Copier:
    def __init__(self, sys_db: Session, user_id: uuid.UUID, source_company_id: uuid.UUID):
        self.db = sys_db
        self.user = user_id
        self.source = source_company_id
        self.media: dict[uuid.UUID, uuid.UUID] = {}   # source media id -> platform media id
        self.colors: set[str] = set()                 # colour codes already ensured in the library
        self.material_codes: set[str] = set()         # material codes already present/created in the library

    # -- media: reuse a platform row with the same content hash, else create one (file is content-addressed on disk)
    def media_id(self, old: uuid.UUID | None) -> uuid.UUID | None:
        if old is None:
            return None
        if old in self.media:
            return self.media[old]
        src = self.db.get(MediaFile, old)
        if src is None:
            return None
        plat = self.db.scalar(select(MediaFile).where(MediaFile.company_id == PLATFORM_COMPANY_ID,
                                                      MediaFile.sha256 == src.sha256))
        if plat is None:
            plat = MediaFile(id=uuid7(), company_id=PLATFORM_COMPANY_ID, sha256=src.sha256, mime=src.mime,
                             filename=src.filename, size=src.size, created_by=self.user)
            self.db.add(plat)
            self.db.flush()
        self.media[old] = plat.id
        return plat.id

    # -- colour: ensure the library has a colour with this code (copy name/hex from the source company)
    def ensure_color(self, code: str) -> None:
        if not code or code in self.colors:
            return
        self.colors.add(code)
        if self.db.scalar(select(Color).where(Color.company_id == PLATFORM_COMPANY_ID, Color.code == code)):
            return
        src = self.db.scalar(select(Color).where(Color.company_id == self.source, Color.code == code))
        self.db.add(Color(id=uuid7(), company_id=PLATFORM_COMPANY_ID, code=code,
                          name=src.name if src else code, hex=src.hex if src else None,
                          is_active=src.is_active if src else True, created_by=self.user))
        self.db.flush()

    # -- material: reuse the library material with the same code, else copy it with its variants
    def copy_material(self, src: Material, new_system_id: uuid.UUID | None) -> None:
        if src.code in self.material_codes:
            return
        self.material_codes.add(src.code)
        if self.db.scalar(select(Material).where(Material.company_id == PLATFORM_COMPANY_ID,
                                                 Material.code == src.code, Material.deleted_at.is_(None))):
            return  # already in the library (by code) — models reference it by code, so reuse it
        mat = Material(id=uuid7(), company_id=PLATFORM_COMPANY_ID, system_id=new_system_id, code=src.code,
                       name=src.name, category=src.category, kind=src.kind, unit=src.unit,
                       bar_length_mm=src.bar_length_mm, min_piece_mm=src.min_piece_mm,
                       weight_kg_per_m=src.weight_kg_per_m, reference_cost=src.reference_cost,
                       image_id=self.media_id(src.image_id), status=src.status, is_active=src.is_active,
                       created_by=self.user)
        self.db.add(mat)
        self.db.flush()
        for v in self.db.scalars(select(MaterialVariant).where(MaterialVariant.material_id == src.id)):
            self.ensure_color(v.color_code)
            if self.db.scalar(select(MaterialVariant).where(MaterialVariant.company_id == PLATFORM_COMPANY_ID,
                                                           MaterialVariant.sku == v.sku)):
                continue  # a SKU is unique per company; keep the existing one
            self.db.add(MaterialVariant(id=uuid7(), company_id=PLATFORM_COMPANY_ID, material_id=mat.id,
                                        color_code=v.color_code, sku=v.sku, name=v.name,
                                        reference_cost=v.reference_cost, is_active=v.is_active))
        self.db.flush()

    def copy_system(self, src: ProfileSystem) -> dict:
        new = ProfileSystem(id=uuid7(), company_id=PLATFORM_COMPANY_ID, code=src.code, name=src.name,
                            supplier=src.supplier, material_type=src.material_type, unit=src.unit,
                            rounding_step_mm=src.rounding_step_mm, rounding_mode=src.rounding_mode,
                            status=src.status, description=src.description, image_id=self.media_id(src.image_id),
                            is_active=src.is_active, current_version_id=None, created_by=self.user)
        self.db.add(new)
        self.db.flush()
        for c in self.db.scalars(select(SystemConstant).where(SystemConstant.system_id == src.id)):
            self.db.add(SystemConstant(id=uuid7(), company_id=PLATFORM_COMPANY_ID, system_id=new.id, name=c.name,
                                       label=c.label, value=c.value, unit=c.unit, description=c.description,
                                       sort=c.sort, created_by=self.user))
        # materials of this system
        mats = self.db.scalars(select(Material).where(Material.system_id == src.id,
                                                      Material.deleted_at.is_(None))).all()
        for m in mats:
            self.copy_material(m, new.id)
        # models (with their test cases); pull in any material referenced only by code
        models = self.db.scalars(select(ProductModel).where(ProductModel.system_id == src.id,
                                                            ProductModel.deleted_at.is_(None))).all()
        for m in models:
            for code in referenced_codes(m.definition or {}) - self.material_codes:
                extra = self.db.scalar(select(Material).where(Material.company_id == self.source,
                                                             Material.code == code, Material.deleted_at.is_(None)))
                if extra is not None:
                    self.copy_material(extra, new.id if extra.system_id == src.id else None)
        for m in models:
            color_images = {k: str(self.media_id(uuid.UUID(v))) for k, v in (m.color_images or {}).items()
                            if self.media_id(uuid.UUID(v))}
            new_model = ProductModel(id=uuid7(), company_id=PLATFORM_COMPANY_ID, system_id=new.id, code=m.code,
                                     name=m.name, category=m.category, description=m.description,
                                     image_id=self.media_id(m.image_id), color_images=color_images,
                                     status=m.status, is_active=m.is_active, sort=m.sort,
                                     definition=m.definition, created_by=self.user)
            self.db.add(new_model)
            self.db.flush()
            for t in self.db.scalars(select(ModelTestCase).where(ModelTestCase.model_id == m.id)):
                self.db.add(ModelTestCase(id=uuid7(), company_id=PLATFORM_COMPANY_ID, model_id=new_model.id,
                                          name=t.name, opening_width_mm=t.opening_width_mm,
                                          opening_height_mm=t.opening_height_mm, params=t.params,
                                          expected=t.expected, created_by=self.user))
        self.db.flush()
        return {"code": src.code, "name": src.name, "models": len(models)}


def copy_systems(sys_db: Session, user_id: uuid.UUID, source_company_id: uuid.UUID,
                 system_ids: list[uuid.UUID]) -> dict:
    """Copy the chosen systems of one company into the platform library. Atomic (caller commits)."""
    copier = _Copier(sys_db, user_id, source_company_id)
    copied: list[dict] = []
    skipped: list[dict] = []
    for sid in system_ids:
        src = sys_db.get(ProfileSystem, sid)
        if src is None or src.company_id != source_company_id or src.deleted_at is not None:
            skipped.append({"id": str(sid), "reason": "not_found"})
            continue
        if sys_db.scalar(select(ProfileSystem).where(ProfileSystem.company_id == PLATFORM_COMPANY_ID,
                                                     ProfileSystem.code == src.code,
                                                     ProfileSystem.deleted_at.is_(None))):
            skipped.append({"code": src.code, "name": src.name, "reason": "code_exists"})
            continue
        copied.append(copier.copy_system(src))
    return {"copied": copied, "skipped": skipped, "colors": sorted(copier.colors),
            "materials": sorted(copier.material_codes)}
