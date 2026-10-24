"""Library packages: vendor export -> sign -> customer preview/apply on a separate database."""
import io
import json
import zipfile
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.licensing.signing import generate_keypair, load_private_key, load_public_key, set_vendor_public_key
from tests.conftest import ADMIN_URL
from tests.library_helpers import build_library

CUSTOMER_DB = "mytech_test_customer"


@pytest.fixture
def key():
    priv, pub = generate_keypair()
    set_vendor_public_key(load_public_key(pub))
    yield load_private_key(priv)
    set_vendor_public_key(None)


@pytest.fixture(scope="module")
def customer_db():
    """A second installation: empty database, same migrations."""
    from app.cli import migrate

    s = get_settings()
    owner = make_url(s.database_owner_url)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{CUSTOMER_DB}"'))
        c.execute(text(f'CREATE DATABASE "{CUSTOMER_DB}" OWNER "{owner.username}"'))
    admin.dispose()
    db_admin = create_engine(ADMIN_URL.rsplit("/", 1)[0] + "/" + CUSTOMER_DB, isolation_level="AUTOCOMMIT")
    with db_admin.connect() as c:
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{owner.username}"'))
        sysrole = make_url(s.database_system_url).username
        c.execute(text(f'GRANT USAGE ON SCHEMA public TO "{sysrole}"'))
        c.execute(text(f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner.username}" IN SCHEMA public '
                       f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{sysrole}"'))
    db_admin.dispose()
    migrate(url=owner.set(database=CUSTOMER_DB).render_as_string(hide_password=False))
    engine = create_engine(make_url(s.database_system_url).set(database=CUSTOMER_DB))
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def _export(client, platform, codes):
    r = client.post("/api/v1/library/packages/export", headers=platform.h, json={"system_codes": codes, "notes": "t"})
    assert r.status_code == 200, r.text
    return r.content


def _sign(data, key):
    from app.modules.library.packages import sign_package
    return sign_package(data, key)


def test_unsigned_or_tampered_package_rejected(platform, tenant_a, client, key):
    build_library(client, platform, code="PKG-SIG")
    raw = _export(client, platform, ["PKG-SIG"])
    files = {"file": ("p.zip", raw, "application/zip")}
    r = client.post("/api/v1/library/packages/preview", headers=tenant_a.h, files=files)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PACKAGE_SIGNATURE_INVALID"

    signed = _sign(raw, key)
    z = zipfile.ZipFile(io.BytesIO(signed))
    doc = json.loads(z.read("package.json"))
    doc["payload"]["systems"][0]["constants"][0]["value"] = "999"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        w.writestr("package.json", json.dumps(doc))
        for n in z.namelist():
            if n != "package.json":
                w.writestr(n, z.read(n))
    r = client.post("/api/v1/library/packages/preview", headers=tenant_a.h,
                    files={"file": ("p.zip", out.getvalue(), "application/zip")})
    assert r.json()["error"]["code"] == "PACKAGE_SIGNATURE_INVALID"

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as w:
        for n in z.namelist():
            w.writestr(n, z.read(n) if not n.startswith("media/") else b"corrupted")
    r = client.post("/api/v1/library/packages/preview", headers=tenant_a.h,
                    files={"file": ("p.zip", out.getvalue(), "application/zip")})
    assert r.json()["error"]["code"] == "PACKAGE_CORRUPTED"


def test_preview_and_apply_through_api(platform, tenant_a, client, key):
    build_library(client, platform, code="PKG-API")
    signed = _sign(_export(client, platform, ["PKG-API"]), key)
    r = client.post("/api/v1/library/packages/preview", headers=tenant_a.h,
                    files={"file": ("p.zip", signed, "application/zip")})
    assert r.status_code == 200, r.text
    assert r.json()["diff"]["systems"][0]["status"] == "unchanged"   # same server already has it
    imp = r.json()["import_id"]
    r = client.post(f"/api/v1/library/packages/{imp}/apply", headers=tenant_a.h)
    assert r.status_code == 200 and r.json()["status"] == "applied"
    assert client.post(f"/api/v1/library/packages/{imp}/apply", headers=tenant_a.h).status_code == 409
    assert client.get("/api/v1/library/packages/imports", headers=tenant_a.h).json()[0]["status"] == "applied"


def test_customer_cannot_export(tenant_a, client):
    r = client.post("/api/v1/library/packages/export", headers=tenant_a.h, json={})
    assert r.status_code == 403


def test_fresh_install_receives_library_and_keeps_calibration(platform, client, key, customer_db):
    from app.engine.compute import calculate
    from app.modules.library.models import (CompanyCalibration, FormulaSetVersion, Material, ProductModel,
                                            ProfileSystem)
    from app.modules.library.packages import apply_package, compute_diff, open_package
    from app.modules.library.service import model_snapshot
    from app.modules.org.service import create_company

    lib = build_library(client, platform, code="PKG-NEW")
    payload, z = open_package(_sign(_export(client, platform, ["PKG-NEW"]), key))

    with customer_db() as db:
        diff = compute_diff(db, payload)
        s = diff["systems"][0]
        assert s["status"] == "new" and s["new_versions"] == [1] and len(s["materials"]["added"]) == 4
        apply_package(db, payload, z)
        company, _ = create_company(db, code="CUST", name="Customer", admin_username="admin",
                                    admin_password="x-pass-1234")
        db.commit()
        system = db.scalar(select(ProfileSystem).where(ProfileSystem.code == "PKG-NEW"))
        assert str(system.id) == lib["system"]["id"]          # same ids everywhere
        version = db.get(FormulaSetVersion, system.current_version_id)
        snap = model_snapshot(version.snapshot, "SL2")
        r = calculate(snap, opening_width_mm=1000, opening_height_mm=1000)
        assert next(p for p in r.pieces if p["key"] == "frame_top")["length_mm"] == D(1006)
        db.add(CompanyCalibration(company_id=company.id, system_id=system.id, constant_name="weld_allowance",
                                  delta=D("0.1")))
        db.commit()
        assert compute_diff(db, payload)["systems"][0]["status"] == "unchanged"

    # vendor changes a constant, removes a model's test, adds a model, republishes
    sid = lib["system"]["id"]
    consts = client.get(f"/api/v1/library/systems/{sid}/constants", headers=platform.h).json()
    weld = next(c for c in consts if c["name"] == "weld_allowance")
    client.patch(f"/api/v1/library/constants/{weld['id']}", headers=platform.h,
                 json={"version": weld["version"], "value": "0.35"})
    for t in client.get(f"/api/v1/library/models/{lib['model']['id']}/tests", headers=platform.h).json():
        client.delete(f"/api/v1/library/tests/{t['id']}", headers=platform.h)
    r = client.post(f"/api/v1/library/systems/{sid}/publish", headers=platform.h, json={"notes": "v2"})
    assert r.status_code == 200, r.text
    payload2, z2 = open_package(_sign(_export(client, platform, ["PKG-NEW"]), key))

    with customer_db() as db:
        diff = compute_diff(db, payload2)["systems"][0]
        assert diff["status"] == "changed" and diff["new_versions"] == [2]
        assert diff["constants"]["changed"] == [{"name": "weld_allowance", "old": "0.300000", "new": "0.350000"}]
        apply_package(db, payload2, z2)
        db.commit()
        system = db.scalar(select(ProfileSystem).where(ProfileSystem.code == "PKG-NEW"))
        assert db.get(FormulaSetVersion, system.current_version_id).version_no == 2
        v1 = db.scalar(select(FormulaSetVersion).where(FormulaSetVersion.system_id == system.id,
                                                       FormulaSetVersion.version_no == 1))
        assert v1.sha256 == lib["version"]["sha256"]          # old version untouched
        cal = db.scalar(select(CompanyCalibration).where(CompanyCalibration.system_id == system.id))
        assert cal.delta == D("0.1")                           # company calibration untouched
        assert db.scalar(select(ProductModel).where(ProductModel.system_id == system.id)).is_active
        assert db.scalar(select(Material).where(Material.code == "PKG-NEW-FRAME")).is_active
