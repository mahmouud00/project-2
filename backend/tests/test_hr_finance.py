"""HR (employees, bonuses / deductions / advances, leave, payroll), the salesperson of each sale, the purchase
approval, assets, profit and capital."""
from datetime import date
from decimal import Decimal as D

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from tests.test_org_permissions_locking import _make_user


def _employee(client, h, branch, **kw):
    r = client.post("/api/v1/employees", headers=h, json={"full_name": "أحمد", "department": "sales",
                                                         "branch_id": branch["id"], "base_salary": "6000", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_payroll_with_bonus_deduction_leave_and_advance(platform, tenant_a, tenant_b, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "HRP")
    h = tenant_a.h
    e = _employee(client, h, branch, national_id="29001011234567", phone="01011111111")
    assert e["code"].startswith("EM-") and e["status"] == "active"
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "HRB", "name": "خزينة", "branch_id": branch["id"]}).json()
    client.post("/api/v1/cash-transactions", headers=h, json={"cashbox_id": box["id"], "direction": "in",
                                                              "amount": "20000", "party_type": "other"})
    month = "2026-03"
    add = lambda **kw: client.post("/api/v1/employee-entries", headers=h, json={"employee_id": e["id"], **kw})
    assert add(kind="bonus", amount="500", entry_date="2026-03-05").status_code == 201
    assert add(kind="deduction", amount="200", entry_date="2026-03-10").status_code == 201
    r = add(kind="advance", amount="1000", entry_date="2026-03-01")
    assert r.status_code == 422 and r.json()["error"]["code"] == "CASHBOX_REQUIRED"
    adv = add(kind="advance", amount="1000", installment="400", entry_date="2026-03-01", cashbox_id=box["id"]).json()
    assert adv["cash_transaction_id"] and D(adv["installment"]) == 400
    lv = client.post("/api/v1/employee-leaves", headers=h, json={
        "employee_id": e["id"], "kind": "unpaid", "start_date": "2026-03-15", "end_date": "2026-03-16"}).json()
    assert D(lv["days"]) == 2
    client.post("/api/v1/employee-leaves", headers=h, json={
        "employee_id": e["id"], "kind": "annual", "start_date": "2026-04-01", "end_date": "2026-04-03"})

    run = client.post("/api/v1/payroll-runs", headers=h, json={"month": month, "branch_id": branch["id"]})
    assert run.status_code == 201, run.text
    run = run.json()
    slip = next(s for s in run["payslips"] if s["employee_id"] == e["id"])
    # 6000 + 500 − 200 − 2 days × 6000/30 = 5900 cost; minus 400 of the advance = 5500 in hand
    assert D(slip["unpaid_leave_deduction"]) == 400 and D(slip["gross"]) == 5900
    assert D(slip["advance_repayment"]) == 400 and D(slip["net"]) == 5500
    again = client.post("/api/v1/payroll-runs", headers=h, json={"month": month, "branch_id": branch["id"]})
    assert again.status_code == 409 and again.json()["error"]["code"] == "PAYROLL_EXISTS"
    paid = client.post(f"/api/v1/payroll-runs/{run['id']}/pay", headers=h,
                       json={"version": run["version"], "cashbox_id": box["id"]})
    assert paid.status_code == 200, paid.text
    paid = paid.json()
    assert paid["status"] == "paid" and paid["payslips"][0]["cash_transaction_id"]
    s = client.get(f"/api/v1/employees/{e['id']}/summary?year=2026", headers=h).json()
    assert D(s["advances_owed"]) == 600 and D(s["annual_leave_left"]) == 18
    assert client.post(f"/api/v1/payroll-runs/{run['id']}/recalculate", headers=h).status_code == 409
    # a paid salary is not reversed; nor is an advance already partly taken back
    r = client.post(f"/api/v1/cash-transactions/{paid['payslips'][0]['cash_transaction_id']}/reverse", headers=h,
                    json={"note": "غلط"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SALARY_PAID"
    r = client.post(f"/api/v1/cash-transactions/{adv['cash_transaction_id']}/reverse", headers=h, json={"note": "غلط"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ADVANCE_REPAID"
    # next month takes the next installment
    run2 = client.post("/api/v1/payroll-runs", headers=h, json={"month": "2026-04", "branch_id": branch["id"]}).json()
    assert D(next(x for x in run2["payslips"] if x["employee_id"] == e["id"])["advance_repayment"]) == 400
    assert len(client.get(f"/api/v1/employees/{e['id']}/payslips", headers=h).json()) == 1
    # personal data reads are logged; another company sees nothing
    client.get(f"/api/v1/employees/{e['id']}", headers=h)
    log = client.get(f"/api/v1/privacy/access-log?subject_id={e['id']}", headers=h).json()["items"]
    assert any(x["subject_type"] == "employee" and "national_id" in x["fields"] for x in log)
    assert client.get(f"/api/v1/employees/{e['id']}", headers=tenant_b.h).status_code == 404
    assert client.get("/api/v1/payroll-runs", headers=tenant_b.h).json()["total"] == 0


def test_salesperson_follows_the_sale(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "SLP")
    h = tenant_a.h
    e = _employee(client, h, branch, full_name="مندوب")
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": "SLP-GLASS6"}
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "salesperson_id": e["id"], "lines": [line]}).json()
    assert q["salesperson_id"] == e["id"]
    q = client.post(f"/api/v1/quotations/{q['id']}/status", headers=h, json={"version": q["version"],
                                                                              "status": "accepted"}).json()
    wo = client.post("/api/v1/work-orders/from-quotation", headers=h, json={"quotation_id": q["id"]}).json()
    assert wo["salesperson_id"] == e["id"]
    inv = client.post("/api/v1/invoices", headers=h, json={"work_order_id": wo["id"]}).json()
    assert inv["salesperson_id"] == e["id"]
    sales = client.get(f"/api/v1/employees/{e['id']}/sales", headers=h).json()
    assert sales["quotations"]["accepted"] == 1 and sales["work_orders"]["count"] == 1
    assert D(sales["work_orders"]["total"]) == D(wo["total"]) and sales["orders"][0]["customer"] == customer["name"]
    assert any(x["id"] == e["id"] for x in client.get("/api/v1/employees/brief?department=sales", headers=h).json())
    # a user linked to an employee is the salesperson of what they sell
    u = _make_user(tenant_a, client, "seller", "sales")
    e2 = _employee(client, h, branch, full_name="بائع", user_id=u["id"])
    hs = tenant_a.headers("seller", "user-pass-123")
    q2 = client.post("/api/v1/quotations", headers=hs, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                           "lines": [line]}).json()
    assert q2["salesperson_id"] == e2["id"]
    # an employee with sales is not deleted, only marked as left
    assert client.delete(f"/api/v1/employees/{e['id']}", headers=h).json()["result"] == "deactivated"


def test_purchase_needs_approval_by_accounts(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "APR")
    h = tenant_a.h
    _make_user(tenant_a, client, "buyer", "production")
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد"}).json()
    po = client.post("/api/v1/purchase-orders", headers=h, json={
        "supplier_id": sup["id"], "branch_id": branch["id"], "lines": [{"sku": "APR-FRAME-W", "qty": "6",
                                                                         "unit_cost": "100"}]}).json()
    _make_user(tenant_a, client, "acc", "accounts")
    ha = tenant_a.headers("acc", "user-pass-123")
    rej = client.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=ha,
                      json={"version": po["version"], "approve": False, "note": "غالي"}).json()
    assert rej["status"] == "rejected"
    r = client.post(f"/api/v1/purchase-orders/{po['id']}/status", headers=h, json={"version": rej["version"],
                                                                                   "status": "ordered"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PO_NOT_APPROVED"
    assert client.delete(f"/api/v1/purchase-orders/{po['id']}", headers=h).json()["result"] == "deleted"
    hb = tenant_a.headers("buyer", "user-pass-123")
    assert client.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=hb,
                       json={"version": 1}).status_code == 403


def test_assets_profit_and_capital(platform, tenant_a, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "FIN")
    h = tenant_a.h
    company = client.get("/api/v1/company", headers=h).json()
    client.patch("/api/v1/company", headers=h, json={"version": company["version"], "settings": {
        **company["settings"], "opening_capital": "100000"}})
    a1 = client.post("/api/v1/assets", headers=h, json={"name": "عربية", "category": "vehicle", "value": "250000"}).json()
    a2 = client.post("/api/v1/assets", headers=h, json={"name": "منشار قديم", "category": "machine", "value": "5000"}).json()
    client.patch(f"/api/v1/assets/{a2['id']}", headers=h, json={"version": a2["version"], "status": "disposed"})
    today = date.today()
    # a sale (issued invoice), a purchase received, an expense and a paid salary this month
    wo = _accepted_order(client, h, lib, branch, customer, "FIN")
    inv = client.post("/api/v1/invoices", headers=h, json={"work_order_id": wo["id"]}).json()
    inv = client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=h, json={"version": inv["version"]}).json()
    sup = client.post("/api/v1/suppliers", headers=h, json={"name": "مورد"}).json()
    po = client.post("/api/v1/purchase-orders", headers=h, json={
        "supplier_id": sup["id"], "branch_id": branch["id"], "lines": [{"sku": "FIN-FRAME-W", "qty": "10",
                                                                         "unit_cost": "50"}]}).json()
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=h, json={"version": po["version"]}).json()
    po = client.post(f"/api/v1/purchase-orders/{po['id']}/status", headers=h, json={"version": po["version"],
                                                                                    "status": "ordered"}).json()
    client.post(f"/api/v1/purchase-orders/{po['id']}/receive", headers=h, json={
        "version": po["version"], "lines": [{"line_id": po["lines"][0]["id"], "qty": "10"}]})
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "FB", "name": "خ", "branch_id": branch["id"]}).json()
    client.post("/api/v1/cash-transactions", headers=h, json={"cashbox_id": box["id"], "direction": "in",
                                                              "amount": "10000", "party_type": "other"})
    client.post("/api/v1/cash-transactions", headers=h, json={"cashbox_id": box["id"], "direction": "out",
                                                              "amount": "300", "party_type": "other", "note": "كهربا"})
    mistake = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "out", "amount": "999", "party_type": "other"}).json()
    client.post(f"/api/v1/cash-transactions/{mistake['id']}/reverse", headers=h, json={"note": "غلط"})
    _employee(client, h, branch, base_salary="2000")
    run = client.post("/api/v1/payroll-runs", headers=h, json={"month": today.strftime("%Y-%m"),
                                                             "branch_id": branch["id"]}).json()
    client.post(f"/api/v1/payroll-runs/{run['id']}/pay", headers=h, json={"version": run["version"],
                                                                            "cashbox_id": box["id"]})
    p = client.get(f"/api/v1/finance/profit?year={today.year}", headers=h).json()
    m = next(x for x in p["months"] if x["month"] == today.strftime("%Y-%m"))
    sales = D(inv["total"]) - D(inv["tax_amount"])
    assert D(m["sales"]) == sales and D(m["purchases"]) == 500 and D(m["expenses"]) == 300
    assert D(m["salaries"]) == 2000 and D(m["profit"]) == sales - 500 - 300 - 2000
    assert p["total"]["profit"] == m["profit"]
    cap = client.get("/api/v1/finance/capital", headers=h).json()
    assert D(cap["assets"]) == 250000 and D(cap["opening_capital"]) == 100000
    assert D(cap["capital"]) == 100000 + 250000 + D(cap["accumulated_profit"])
    assert D(cap["accumulated_profit"]) == D(m["profit"])
    # the company's money is hidden from users who do not manage it
    _make_user(tenant_a, client, "sl", "sales")
    hs = tenant_a.headers("sl", "user-pass-123")
    assert "opening_capital" not in client.get("/api/v1/company", headers=hs).json()["settings"]
    assert client.get("/api/v1/finance/profit", headers=hs).status_code == 403
    assert a1["status"] == "active"


def test_sale_needs_accounts_and_notifications_reach_each_section(platform, tenant_a, tenant_b, client):
    lib, branch, pl, customer = _setup(client, platform, tenant_a, "NTF")
    h = tenant_a.h
    _make_user(tenant_a, client, "acc2", "accounts")
    _make_user(tenant_a, client, "smgr", "sales_manager")
    _make_user(tenant_a, client, "pmgr", "production_manager")
    _make_user(tenant_a, client, "fmgr", "field_manager")
    ha, hs, hp, hf = (tenant_a.headers(u, "user-pass-123") for u in ("acc2", "smgr", "pmgr", "fmgr"))
    inbox = lambda hh: client.get("/api/v1/notifications", headers=hh).json()
    # a customer change reaches the sales manager only
    client.patch(f"/api/v1/customers/{customer['id']}", headers=h, json={"version": customer["version"], "phone": "0123"})
    assert any(customer["name"] in n["title"] for n in inbox(hs)["items"])
    assert inbox(hp)["unread"] == 0 and inbox(hf)["unread"] == 0
    # a sale waits for the accounts, who are notified
    wo = _accepted_order(client, h, lib, branch, customer, "NTF")
    assert wo["sale_status"] == "pending"
    note = next(n for n in inbox(ha)["items"] if wo["number"] in n["title"])
    assert note["link"] == "treasury?tab=sales" and note["read_at"] is None
    pending = client.get("/api/v1/work-orders?sale_status=pending", headers=ha).json()["items"]
    assert [x["id"] for x in pending] == [wo["id"]]
    r = client.post(f"/api/v1/work-orders/{wo['id']}/approve-sale", headers=hs, json={"version": wo["version"]})
    assert r.status_code == 403       # only the accounts confirm a sale
    wo = client.post(f"/api/v1/work-orders/{wo['id']}/approve-sale", headers=ha,
                     json={"version": wo["version"], "note": "العربون تمام"}).json()
    assert wo["sale_status"] == "approved" and wo["sale_approval_note"] == "العربون تمام"
    assert any("جاهز للتصنيع" in n["title"] for n in inbox(hp)["items"])
    # the one who acted is not notified of their own change; reading clears the count
    assert not any("أكدت" in n["title"] for n in inbox(ha)["items"])
    n = inbox(hs)
    assert n["unread"] >= 2
    assert client.post("/api/v1/notifications/read-all", headers=hs).json()["unread"] == 0
    # technicians' jobs reach the installations manager and the technician
    tech = _make_user(tenant_a, client, "tech9", "technician")
    from datetime import datetime, timedelta, timezone
    job = client.post("/api/v1/field/jobs", headers=h, json={
        "kind": "installation", "customer_id": customer["id"], "branch_id": branch["id"], "work_order_id": wo["id"],
        "technician_id": tech["id"], "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}).json()
    ht = tenant_a.headers("tech9", "user-pass-123")
    assert any("عندك مهمة" in x["title"] for x in inbox(ht)["items"])
    client.post(f"/api/v1/field/jobs/{job['id']}/status", headers=ht, json={"status": "on_way"})
    assert any("في الطريق" in x["title"] for x in inbox(hf)["items"])
    # polling for what is new; nobody else's notifications, no other company's
    after = inbox(hf)["items"][0]["created_at"]
    assert client.get("/api/v1/notifications", params={"after": after}, headers=hf).json()["items"] == []
    assert inbox(tenant_b.h)["items"] == []
