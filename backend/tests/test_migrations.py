"""Every migration must keep existing data: seed at an old revision, upgrade to head, compare."""
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from tests.conftest import ADMIN_URL

MIG_DB = "mytech_test_migrations"


def test_upgrade_from_old_revision_keeps_data():
    from app.cli import migrate

    s = get_settings()
    owner = make_url(s.database_owner_url)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        c.execute(text(f'CREATE DATABASE "{MIG_DB}" OWNER "{owner.username}"'))
    admin.dispose()
    db_admin = create_engine(ADMIN_URL.rsplit("/", 1)[0] + "/" + MIG_DB, isolation_level="AUTOCOMMIT")
    with db_admin.connect() as c:
        c.execute(text(f'ALTER SCHEMA public OWNER TO "{owner.username}"'))
    db_admin.dispose()
    url = owner.set(database=MIG_DB).render_as_string(hide_password=False)

    migrate(url=url, revision="0001")
    cid, uid = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO companies (id, company_id, code, name, is_active, settings, version) "
                       "VALUES (:i, :i, 'OLD', 'Old company', true, '{\"currency\": \"EGP\"}', 3)"), {"i": cid})
        c.execute(text("INSERT INTO users (id, company_id, username, password_hash, full_name, is_active, "
                       "failed_logins, must_change_password, version) VALUES (:u, :c, 'old', 'h', 'Old user', true, "
                       "0, false, 2)"), {"u": uid, "c": cid})
    before = _dump(engine)
    engine.dispose()

    migrate(url=url, revision="0002")
    engine = create_engine(url)
    with engine.begin() as c:
        sid = uuid.uuid4()
        c.execute(text("INSERT INTO profile_systems (id, company_id, code, name, supplier, material_type, unit, "
                       "rounding_step_mm, rounding_mode, status, description, is_active, version) VALUES "
                       "(:s, :c, 'S', 'Sys', '', 'upvc', 'cm', 0, 'half_up', 'approved', '', true, 1)"),
                  {"s": sid, "c": cid})
    before2 = _dump(engine)
    engine.dispose()

    migrate(url=url, revision="0003")
    engine = create_engine(url)
    with engine.begin() as c:
        bid, box, tx = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        c.execute(text("INSERT INTO branches (id, company_id, code, name, kind, is_active, version) "
                       "VALUES (:b, :c, 'MAIN', 'Main', 'factory', true, 1)"), {"b": bid, "c": cid})
        c.execute(text("INSERT INTO cashboxes (id, company_id, code, name, branch_id, is_active, version) "
                       "VALUES (:x, :c, 'BOX', 'Box', :b, true, 1)"), {"x": box, "c": cid, "b": bid})
        c.execute(text("INSERT INTO cash_transactions (id, company_id, number, at, cashbox_id, direction, amount, "
                       "method, party_type, reference, note, reversed) VALUES (:t, :c, 'CT-1', now(), :x, "
                       "'in', 125.50, 'cash', 'other', '', 'old receipt', false)"), {"t": tx, "c": cid, "x": box})
    before3 = _dump(engine)
    engine.dispose()

    migrate(url=url, revision="0004")
    engine = create_engine(url)
    with engine.begin() as c:
        ids = {k: uuid.uuid4() for k in ("model", "fsv", "cust", "pl", "sv", "op", "q", "ql")}
        p = {**{k: v for k, v in ids.items()}, "c": cid, "s": sid, "b": bid}
        c.execute(text("INSERT INTO product_models (id, company_id, system_id, code, name, category, description, "
                       "status, is_active, sort, definition, version) VALUES (:model, :c, :s, 'M1', 'Model', 'window', "
                       "'', 'approved', true, 0, '{}', 1)"), p)
        c.execute(text("INSERT INTO formula_set_versions (id, company_id, system_id, version_no, snapshot, sha256, notes, "
                       "published_at, version) VALUES (:fsv, :c, :s, 1, '{}', 'x', '', now(), 1)"), p)
        c.execute(text("INSERT INTO customers (id, company_id, code, name, customer_type, anonymized, version) "
                       "VALUES (:cust, :c, 'CU-1', 'Old customer', 'end', false, 1)"), p)
        c.execute(text("INSERT INTO price_lists (id, company_id, code, name, margin_pct, labor_cost_per_m2, "
                       "min_unit_price, is_active, version) VALUES (:pl, :c, 'PL', 'List', 20, 0, 0, true, 1)"), p)
        c.execute(text("INSERT INTO site_surveys (id, company_id, number, customer_id, branch_id, status, notes, version) "
                       "VALUES (:sv, :c, 'SV-1', :cust, :b, 'open', 'old survey', 1)"), p)
        c.execute(text("INSERT INTO survey_openings (id, company_id, survey_id, position, location, opening_width_mm, "
                       "opening_height_mm, qty, params, notes, version) VALUES (:op, :c, :sv, 1, 'kitchen', 800, 600, "
                       "2, '{}', '', 1)"), p)
        c.execute(text("INSERT INTO quotations (id, company_id, number, customer_id, branch_id, price_list_id, status, "
                       "discount_amount, tax_pct, subtotal, tax_amount, total, total_cost, notes, terms, version) VALUES "
                       "(:q, :c, 'QT-1', :cust, :b, :pl, 'draft', 0, 0, 300, 0, 300, 200, '', '', 1)"), p)
        p["admin_role"], p["sales_role"] = uuid.uuid4(), uuid.uuid4()
        c.execute(text("INSERT INTO roles (id, company_id, code, name, permissions, is_builtin, version) VALUES "
                       "(:admin_role, :c, 'admin', 'مدير', ARRAY['customers.read','customers.write'], true, 1), "
                       "(:sales_role, :c, 'sales2', 'مبيعات', ARRAY['customers.read','customers.write','quotes.read'], "
                       "false, 1)"), p)
        c.execute(text("INSERT INTO quotation_lines (id, company_id, quotation_id, position, location, model_id, "
                       "formula_set_version_id, opening_width_mm, opening_height_mm, params, qty, area_m2, unit_cost, "
                       "unit_price, line_total, calc, cost_breakdown, notes, version) VALUES (:ql, :c, :q, 1, 'kitchen', "
                       ":model, :fsv, 800, 600, '{}', 2, 0.48, 100, 150, 300, '{}', '{}', '', 1)"), p)
    before4 = _dump(engine)
    engine.dispose()

    migrate(url=url)  # head
    engine = create_engine(url)
    after = _dump(engine)
    engine.dispose()
    assert after["cash_transactions"][str(tx)]["invoice_id"] is None
    # 0005: old surveys are window surveys, old lines keep their price and bill their real area
    assert after["site_surveys"][str(ids["sv"])]["kind"] == "window"
    assert after["survey_openings"][str(ids["op"])]["application"] == ""
    line = after["quotation_lines"][str(ids["ql"])]
    assert line["price_per_m2"] is None and line["total_height_mm"] is None and float(line["billed_area_m2"]) == 0.48 and float(line["line_total"]) == 300
    # 0009: whoever could edit customers can still add them; only the built-in admin gets delete
    admin_perms = set(after["roles"][str(p["admin_role"])]["permissions"])
    sales_perms = set(after["roles"][str(p["sales_role"])]["permissions"])
    assert {"customers.create", "customers.delete", "invoices.delete"} <= admin_perms
    assert "customers.create" in sales_perms and "customers.delete" not in sales_perms and "quotes.create" not in sales_perms
    # 0010: surveys get an empty location; admin gets maintenance/field; every company gets a technician role
    assert after["site_surveys"][str(ids["sv"])]["location_url"] is None
    assert {"maintenance.delete", "field.manage"} <= set(after["roles"][str(p["admin_role"])]["permissions"])
    assert "maintenance.create" in set(after["roles"][str(p["sales_role"])]["permissions"])
    techs = [r for r in after["roles"].values() if r["code"] == "technician" and r["company_id"] == str(cid)]
    assert len(techs) == 1 and techs[0]["permissions"] == ["field.self"] and techs[0]["is_builtin"]
    after["roles"] = {k: v for k, v in after["roles"].items() if v["code"] != "technician"}
    for table, rows in {**before, **before2, **before3, **before4}.items():
        assert set(after[table]) == set(rows), f"rows lost or added in {table}"
        for row_id, old in rows.items():
            new = after[table][row_id]
            # new columns may appear; every old value must be unchanged
            if table == "roles":       # permissions only grow (0009); every permission a role had is kept
                assert set(old["permissions"]) <= set(new["permissions"])
                old = {k: v for k, v in old.items() if k != "permissions"}
            assert {k: new.get(k) for k in old} == old, f"data changed in {table} {row_id}"


def _dump(engine) -> dict:
    import json

    out = {}
    with engine.connect() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                                "AND tablename <> 'alembic_version'")).scalars().all()
        for t in tables:
            rows = [json.loads(r) for r in c.execute(text(f'SELECT row_to_json(x)::text FROM "{t}" x')).scalars()]
            if rows:
                out[t] = {r["id"]: r for r in rows}
    return out
