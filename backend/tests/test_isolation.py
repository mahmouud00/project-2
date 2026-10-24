"""A user of one company must never reach another company's data, by any route."""
import uuid

from sqlalchemy import select, text


def test_api_cannot_see_or_touch_other_company(tenant_a, tenant_b, client):
    b_branch = client.post("/api/v1/branches", headers=tenant_b.h, json={"code": "BX", "name": "B secret"}).json()
    a_branches = client.get("/api/v1/branches", headers=tenant_a.h).json()["items"]
    assert all(br["id"] != b_branch["id"] for br in a_branches)
    r = client.patch(f"/api/v1/branches/{b_branch['id']}", headers=tenant_a.h,
                     json={"version": b_branch["version"], "name": "hacked"})
    assert r.status_code == 404
    b_users = client.get("/api/v1/users", headers=tenant_b.h).json()["items"]
    assert client.get(f"/api/v1/users/{b_users[0]['id']}", headers=tenant_a.h).status_code == 404
    # cannot assign another company's role to own user
    b_role = client.get("/api/v1/roles", headers=tenant_b.h).json()[0]
    r = client.post("/api/v1/users", headers=tenant_a.h, json={
        "username": "x1", "password": "user-pass-123", "full_name": "x",
        "assignments": [{"role_id": b_role["id"]}]})
    assert r.status_code == 404


def test_company_id_in_body_is_ignored(tenant_a, tenant_b, client):
    r = client.post("/api/v1/branches", headers=tenant_a.h,
                    json={"code": "INJ", "name": "inj", "company_id": str(tenant_b.id)})
    assert r.status_code == 201
    assert all(b["code"] != "INJ" for b in client.get("/api/v1/branches", headers=tenant_b.h).json()["items"])


def test_rls_blocks_even_without_orm_filter(tenant_a, tenant_b):
    """Raw SQL on the app role with the ORM filter bypassed still sees only one company."""
    from app.db.session import tenant_session
    from app.modules.org.models import Branch

    with tenant_session(tenant_a.id) as db:
        rows = db.execute(select(Branch).execution_options(skip_tenant_filter=True)).scalars().all()
        assert rows and {r.company_id for r in rows} == {tenant_a.id}
        raw = db.execute(text("SELECT DISTINCT company_id FROM branches")).scalars().all()
        assert raw == [tenant_a.id]
        # inserting a row for another company is refused by WITH CHECK
        import pytest
        from sqlalchemy.exc import ProgrammingError
        with pytest.raises(ProgrammingError):
            db.execute(text("INSERT INTO branches (id, company_id, code, name, kind, is_active, version) "
                            "VALUES (:i, :c, 'Z', 'Z', 'factory', true, 1)"), {"i": uuid.uuid4(), "c": tenant_b.id})
        db.rollback()


def test_no_company_context_sees_nothing(tenant_a):
    from app.db.session import app_engine

    with app_engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM branches")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM users")).scalar() == 0


def test_every_tenant_table_has_rls(database):
    from app.db.base import Base, TenantMixin
    from app.db.session import system_engine

    with system_engine().connect() as c:
        rls = dict(c.execute(text("SELECT relname, relrowsecurity AND relforcerowsecurity FROM pg_class "
                                  "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace")).all())
    tenant_tables = [m.class_.__tablename__ for m in Base.registry.mappers if issubclass(m.class_, TenantMixin)]
    missing = [t for t in tenant_tables if not rls.get(t)]
    assert not missing, f"tables without RLS: {missing}"


def test_cross_company_login_refused(tenant_a, tenant_b, client):
    r = client.post("/api/v1/auth/login", json={"company_code": tenant_b.code, "username": "admin",
                                                "password": "wrong-for-b", "device_key": "dev-cross-1"})
    assert r.status_code == 401
