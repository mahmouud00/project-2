"""Test harness: a fresh PostgreSQL database per session, real RLS, real migrations."""
from __future__ import annotations

import os
import uuid

import pytest

ADMIN_URL = os.environ.get("TEST_ADMIN_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/postgres")
TEST_DB = os.environ.get("TEST_DB_NAME", "mytech_test")
os.environ.update({
    "APP_MODE": "offline",
    "DATABASE_URL": f"postgresql+psycopg://mytech_app:testapp@localhost:5432/{TEST_DB}",
    "DATABASE_SYSTEM_URL": f"postgresql+psycopg://mytech_system:testsystem@localhost:5432/{TEST_DB}",
    "DATABASE_OWNER_URL": f"postgresql+psycopg://mytech_owner:testowner@localhost:5432/{TEST_DB}",
    "JWT_SECRET": "test-secret-0123456789-0123456789-abcdef",
})

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


def _drop_db():
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d"), {"d": TEST_DB})
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database(tmp_path_factory):
    from app.cli import init_db, migrate
    from app.db.session import reset_engines

    s = get_settings()
    s.media_dir = tmp_path_factory.mktemp("media")
    s.license_file = tmp_path_factory.mktemp("license") / "license.json"
    s.backup_dir = tmp_path_factory.mktemp("backups")
    _drop_db()
    init_db(ADMIN_URL)
    migrate()
    reset_engines()
    yield
    reset_engines()


@pytest.fixture(autouse=True)
def full_license():
    """Default: everything licensed. Licence tests install their own provider."""
    from app.licensing.provider import FULL, set_license_provider

    class _Full:
        def entitlements(self, db, company_id):
            return FULL

    set_license_provider(_Full())
    yield
    set_license_provider(None)


@pytest.fixture(scope="session")
def app():
    from app.main import create_app
    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


class Tenant:
    def __init__(self, client, company, admin_password):
        self.client = client
        self.company = company
        self.code = company.code
        self.id = company.id
        self.admin_password = admin_password
        self._token = None

    def login(self, username="admin", password=None, device_key="test-device-01") -> dict:
        r = self.client.post("/api/v1/auth/login", json={
            "company_code": self.code, "username": username, "password": password or self.admin_password,
            "device_key": device_key})
        assert r.status_code == 200, r.text
        return r.json()

    def headers(self, username="admin", password=None) -> dict:
        tok = self.login(username, password)["access_token"]
        return {"Authorization": f"Bearer {tok}"}

    @property
    def h(self) -> dict:
        if self._token is None:
            self._token = self.login()["access_token"]
        return {"Authorization": f"Bearer {self._token}"}


def make_company(client, code=None) -> Tenant:
    from app.db.session import system_session
    from app.modules.org.service import create_company

    code = code or "C" + uuid.uuid4().hex[:8].upper()
    with system_session() as db:
        company, _ = create_company(db, code=code, name=f"Company {code}", admin_username="admin",
                                    admin_password="admin-pass-123")
        db.commit()
    return Tenant(client, company, "admin-pass-123")


@pytest.fixture
def tenant_a(client):
    return make_company(client)


@pytest.fixture
def tenant_b(client):
    return make_company(client)


@pytest.fixture
def platform(client):
    """The vendor (library author) logged in on the platform company."""
    from app.db.base import PLATFORM_COMPANY_ID
    from app.db.session import system_session
    from app.modules.org.models import User
    from app.modules.org.service import create_platform_admin, ensure_platform_company
    from sqlalchemy import select

    with system_session() as db:
        ensure_platform_company(db)
        if not db.scalar(select(User).where(User.company_id == PLATFORM_COMPANY_ID, User.username == "vendor")):
            create_platform_admin(db, "vendor", "vendor-pass-123")
        db.commit()
        from app.modules.org.models import Company
        company = db.get(Company, PLATFORM_COMPANY_ID)
    t = Tenant(client, company, "vendor-pass-123")
    t.login = lambda username="vendor", password=None, device_key="vendor-dev-01": Tenant.login(
        t, username, password, device_key)
    return t
