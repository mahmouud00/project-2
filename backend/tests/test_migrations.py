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

    # 0011 drops the warehouse module (the owner's decision); purchase orders and work orders stay
    migrate(url=url, revision="0010")
    engine = create_engine(url)
    with engine.begin() as c:
        p["wh"], p["sup"], p["po"], p["wo"], p["wh_role"], p["acc_role"] = (uuid.uuid4() for _ in range(6))
        c.execute(text("INSERT INTO warehouses (id, company_id, code, name, branch_id, is_active, version) "
                       "VALUES (:wh, :c, 'W', 'Store', :b, true, 1)"), p)
        c.execute(text("INSERT INTO stock_movements (id, company_id, at, warehouse_id, sku, qty, unit, kind, note) "
                       "VALUES (gen_random_uuid(), :c, now(), :wh, 'X', 5, 'm', 'receipt', '')"), p)
        c.execute(text("INSERT INTO suppliers (id, company_id, code, name, notes, version) "
                       "VALUES (:sup, :c, 'SU-1', 'Supplier', '', 1)"), p)
        c.execute(text("INSERT INTO purchase_orders (id, company_id, number, supplier_id, branch_id, warehouse_id, "
                       "status, total, received_value, paid_amount, notes, version) VALUES (:po, :c, 'PO-1', :sup, :b, "
                       ":wh, 'received', 600, 600, 0, 'old po', 2)"), p)
        c.execute(text("INSERT INTO work_orders (id, company_id, number, customer_id, branch_id, warehouse_id, stage, "
                       "total, deposit_required, paid_amount, notes, outputs, materials_issued, version) VALUES "
                       "(:wo, :c, 'WO-1', :cust, :b, :wh, 'manufacturing', 300, 0, 0, '', '{}', true, 3)"), p)
        c.execute(text("INSERT INTO roles (id, company_id, code, name, permissions, is_builtin, version) VALUES "
                       "(:wh_role, :c, 'warehouse', 'مخازن', ARRAY['inventory.read','purchasing.read'], true, 1), "
                       "(:acc_role, :c, 'accounts', 'حسابات', ARRAY['treasury.write','inventory.read'], true, 1)"), p)
        p["mat"], p["cms"] = uuid.uuid4(), uuid.uuid4()
        c.execute(text("INSERT INTO materials (id, company_id, code, name, category, kind, unit, status, is_active, version) "
                       "VALUES (:mat, :c, 'OWN-1', 'Own profile', '', 'profile', 'm', 'approved', true, 1)"), p)
        c.execute(text("INSERT INTO company_material_settings (id, company_id, material_id, color_code, unit_cost, "
                       "is_hidden, version) VALUES (:cms, :c, :mat, '', 123.5, false, 1)"), p)
    before5 = _dump(engine)
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
    # 0011: no warehouse tables or links; orders kept; inventory permissions gone; accounts confirm purchases
    for t in ("warehouses", "stock_movements", "stock_balances", "stock_transfers"):
        assert t not in after
    po = after["purchase_orders"][str(p["po"])]
    assert "warehouse_id" not in po and po["status"] == "received" and float(po["received_value"]) == 600
    assert po["approval_note"] == "" and po["approved_at"] is None
    wo = after["work_orders"][str(p["wo"])]
    assert "materials_issued" not in wo and wo["stage"] == "manufacturing" and wo["salesperson_id"] is None
    assert str(p["wh_role"]) not in after["roles"]           # unused built-in warehouse role removed
    acc = set(after["roles"][str(p["acc_role"])]["permissions"])
    assert {"purchasing.approve", "finance.read", "hr.read", "hr.payroll", "treasury.write"} <= acc
    assert not any(x.startswith("inventory.") for r in after["roles"].values() for x in r["permissions"])
    assert {"hr.create", "purchasing.approve"} <= set(after["roles"][str(p["admin_role"])]["permissions"])
    hr = [r for r in after["roles"].values() if r["code"] == "hr" and r["company_id"] == str(cid)]
    assert len(hr) == 1 and hr[0]["is_builtin"]
    # 0014: an existing company price keeps no discount
    cms = after["company_material_settings"][str(p["cms"])]
    assert cms["discount_pct"] is None and float(cms["unit_cost"]) == 123.5
    # 0015: old quotations keep their price list and price, and need no approval; admin approves low prices
    qt = after["quotations"][str(ids["q"])]
    assert qt["fair_total"] == 0 and qt["price_approved_total"] is None and qt["price_list_id"] is not None
    assert "quotes.approve_price" in set(after["roles"][str(p["admin_role"])]["permissions"])
    assert not any(x.startswith("pricelists.") for r in after["roles"].values() for x in r["permissions"])
    # 0012: orders already in production count as confirmed sales; accounts confirm sales; manager roles
    assert wo["sale_status"] == "approved" and wo["sale_approval_note"] == "قبل تأكيد الحسابات"
    assert {"sales.approve", "notify.accounts"} <= acc
    assert {"notify.sales", "notify.field", "sales.approve"} <= set(after["roles"][str(p["admin_role"])]["permissions"])
    for code in ("sales_manager", "production_manager", "field_manager"):
        assert [r for r in after["roles"].values() if r["code"] == code and r["company_id"] == str(cid)]
    after["roles"] = {k: v for k, v in after["roles"].items() if v["code"] not in (
        "technician", "hr", "sales_manager", "production_manager", "field_manager")}
    for t in ("warehouses", "stock_movements"):
        before5.pop(t)
    before5["roles"] = {k: v for k, v in before5["roles"].items()
                        if k != str(p["wh_role"]) and v["code"] != "technician"}
    for table, rows in {**before, **before2, **before3, **before4, **before5}.items():
        assert set(after[table]) == set(rows), f"rows lost or added in {table}"
        for row_id, old in rows.items():
            new = after[table][row_id]
            # new columns may appear; every old value must be unchanged
            if table == "roles":       # permissions only grow (0009), except the removed inventory (0011) and
                # price list (0015) ones
                assert {x for x in old["permissions"] if not x.startswith(("inventory.", "pricelists."))} <= \
                    set(new["permissions"])
                old = {k: v for k, v in old.items() if k != "permissions"}
            if table == "companies":   # 0013: companies that never set it keep offcuts of 40 cm
                assert new["settings"]["min_reusable_offcut_mm"] == "400"
                new = {**new, "settings": {k: v for k, v in new["settings"].items() if k != "min_reusable_offcut_mm"}}
            if table == "purchase_orders":
                old = {k: v for k, v in old.items() if k != "warehouse_id"}
            if table == "work_orders":
                old = {k: v for k, v in old.items() if k not in ("warehouse_id", "materials_issued")}
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
