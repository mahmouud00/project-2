"""Pay policies from the company's papers: lateness, absence, overtime, installation / travel days by place, work on
the day off, the phone punch, and the sales commission on collections; all of it in the month's payroll."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from tests.test_business_flow import _setup
from tests.test_field_service import _accepted_order
from tests.test_org_permissions_locking import _make_user

SN = "PAYTEST0001"
CAIRO = ("30.050000", "31.240000")
ALEX = ("31.200000", "29.920000")


def _send(client, lines, sn=SN):
    r = client.post(f"/iclock/cdata?SN={sn}&table=ATTLOG", content="".join(lines))
    assert r.status_code == 200, r.text


def _month_lines(pin, start="09:00", end="17:00", skip=(), special=None, fridays=False):
    """October 2026, every working day (Friday off) in at `start`, out at `end`, except `special` {day: (in, out)}."""
    special, lines = special or {}, []
    for n in range(1, 32):
        d = date(2026, 10, n)
        if n in skip or (d.weekday() == 4 and n not in special and not fridays):
            continue
        times = special.get(n, (start, end))
        for t in times:
            if t:
                lines.append(f"{pin}\t{d.isoformat()} {t}:00\t0\t1\n")
    return lines


def _employee(client, h, branch, name, pin, policy, salary, user_id=None, department="other"):
    r = client.post("/api/v1/employees", headers=h, json={
        "full_name": name, "department": department, "branch_id": branch["id"], "base_salary": str(salary),
        "attendance_pin": pin, "pay_policy_id": policy["id"], "user_id": user_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_policies_in_the_payroll(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "PAYP")
    h = tenant_a.h
    pols = {p["code"]: p for p in client.post("/api/v1/pay-policies/templates", headers=h).json()}
    assert set(pols) == {"OFFICE", "SALES", "FACTORY", "INSTALL"}
    assert pols["SALES"]["rules"]["commission_rate"] == "0.01"
    # templates again: nothing doubled
    assert len(client.post("/api/v1/pay-policies/templates", headers=h).json()) == 4
    zones = {z["name"]: z for z in client.get("/api/v1/work-zones", headers=h).json()}
    assert {"القاهرة", "الجيزة", "العاشر من رمضان", "العبور"} <= set(zones)
    cairo = zones["القاهرة"]
    client.patch(f"/api/v1/work-zones/{cairo['id']}", headers=h, json={"version": cairo["version"], "transport_allowance": "50"})
    # a wrong value in a policy is refused
    bad = client.patch(f"/api/v1/pay-policies/{pols['OFFICE']['id']}", headers=h, json={
        "version": pols["OFFICE"]["version"], "rules": {**pols["OFFICE"]["rules"], "work_start": "25:00"}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "POLICY_INVALID"

    assert client.post("/api/v1/attendance/devices", headers=h, json={"serial": SN}).status_code == 201
    tech = _make_user(tenant_a, client, "pay-tech", "technician")
    office = _employee(client, h, branch, "إداري", "11", pols["OFFICE"], 6000)        # a day 200
    factory = _employee(client, h, branch, "فني مصنع", "12", pols["FACTORY"], 9000)   # a day 300, an hour 33.33
    install = _employee(client, h, branch, "فني تركيب", "13", pols["INSTALL"], 9000, tech["id"])

    # office: 9:40 late (> 30 min grace: half a day), 9:20 nothing; absent 7, 8 without notice (2 then 4 days),
    # 11 with notice (1 day)
    _send(client, _month_lines("11", skip=(7, 8, 11), special={5: ("09:40", "17:00"), 6: ("09:20", "17:00")}))
    r = client.put(f"/api/v1/attendance/days/{office['id']}/2026-10-11", headers=h, json={"excuse": "notified"})
    assert r.status_code == 200, r.text
    # factory: 30 min late made up by staying till 18:30; 70 min late (x1.5 = 105 min); 2 hours overtime (x1.5)
    _send(client, _month_lines("12", end="18:00", special={5: ("09:30", "18:30"), 6: ("10:10", "18:00"),
                                                            7: ("09:00", "20:00")}))
    # installation: 5 in Cairo (from 7 to 17: 1 hour over 9), 6 in Alexandria (travel: meal), absent on 7 (job day:
    # 3 days), Friday 9 worked (2 days)
    _send(client, _month_lines("13", end="18:00", skip=(7,), special={5: ("07:00", "17:00"), 6: ("06:00", "15:00"),
                                                                       9: ("09:00", "17:00")}))
    from app.db.session import tenant_session
    from app.modules.field.models import FieldJob

    db = tenant_session(tenant_a.id)
    for n, (lat, lon) in ((5, CAIRO), (6, ALEX), (7, CAIRO)):
        db.add(FieldJob(kind="installation", customer_id=customer["id"], branch_id=branch["id"],
                        technician_id=tech["id"], scheduled_at=datetime(2026, 10, n, 6, 0, tzinfo=timezone.utc),
                        status="done", latitude=D(lat), longitude=D(lon), notes="", result_note=""))
    db.commit()
    db.close()

    m = client.get(f"/api/v1/attendance/month?employee_id={office['id']}&month=2026-10", headers=h).json()
    days = {d["day"]: d for d in m["days"]}
    assert days["2026-10-05"]["deduct_days"] == "0.5" and days["2026-10-06"]["deduct_days"] == "0"
    assert [days[f"2026-10-0{n}"]["deduct_days"] for n in (7, 8)] == ["2", "4"]
    assert days["2026-10-11"]["deduct_days"] == "1" and days["2026-10-02"]["kind"] == "off"
    assert m["attendance_deduction"] == "1500.00" and m["absent_days"] == "3"

    i = client.get(f"/api/v1/attendance/month?employee_id={install['id']}&month=2026-10", headers=h).json()
    days = {d["day"]: d for d in i["days"]}
    assert days["2026-10-05"]["kind"] == "install" and days["2026-10-05"]["overtime"] == 60
    assert days["2026-10-06"]["kind"] == "travel" and days["2026-10-06"]["extra"] == "125.00"
    assert days["2026-10-07"]["kind"] == "absent" and days["2026-10-07"]["deduct_days"] == "3"
    assert days["2026-10-09"]["kind"] == "off" and days["2026-10-09"]["extra"] == "600.00"

    # a permission: at most 120 minutes, twice a month
    assert client.put(f"/api/v1/attendance/days/{office['id']}/2026-10-12", headers=h,
                      json={"excuse": "permission", "permission_minutes": 180}).json()["error"]["code"] == "PERMISSION_TOO_LONG"
    for n in (12, 13):
        assert client.put(f"/api/v1/attendance/days/{office['id']}/2026-10-{n}", headers=h,
                          json={"excuse": "permission", "permission_minutes": 60}).status_code == 200
    assert client.put(f"/api/v1/attendance/days/{office['id']}/2026-10-14", headers=h,
                      json={"excuse": "permission", "permission_minutes": 60}).json()["error"]["code"] == "PERMISSIONS_USED"

    run = client.post("/api/v1/payroll-runs", headers=h, json={"month": "2026-10", "branch_id": branch["id"]})
    assert run.status_code == 201, run.text
    slips = {s["employee_id"]: s for s in run.json()["payslips"]}
    o, f, t = slips[office["id"]], slips[factory["id"]], slips[install["id"]]
    assert o["attendance_deduction"] == "1500.00" and o["net"] == "4500.00" and o["late_minutes"] == 60
    assert f["attendance_deduction"] == "58.33" and f["overtime_minutes"] == 120 and f["overtime_amount"] == "100.00"
    assert f["net"] == "9041.67"
    assert t["attendance_deduction"] == "900.00" and t["overtime_amount"] == "50.00" and t["allowances"] == "775.00"
    assert t["net"] == "8925.00" and t["policy_name"] == "التركيبات"


def test_phone_punch_and_two_morning_punches(platform, tenant_a, client):
    from app.modules.hr.policy import local_now

    lib, branch, _, customer = _setup(client, platform, tenant_a, "PAYA")
    h = tenant_a.h
    pols = {p["code"]: p for p in client.post("/api/v1/pay-policies/templates", headers=h).json()}
    assert client.post("/api/v1/attendance/devices", headers=h, json={"serial": "PAYTEST0002"}).status_code == 201
    tech = _make_user(tenant_a, client, "app-tech", "technician")
    office_user = _make_user(tenant_a, client, "app-office", "sales")
    e = _employee(client, h, branch, "فني", "21", pols["INSTALL"], 9000, tech["id"])
    _employee(client, h, branch, "إداري", "22", pols["OFFICE"], 6000, office_user["id"])
    ht = tenant_a.headers("app-tech", "user-pass-123")
    ho = tenant_a.headers("app-office", "user-pass-123")
    manager = _make_user(tenant_a, client, "app-fm", "field_manager")
    hm = tenant_a.headers("app-fm", "user-pass-123")

    assert client.get("/api/v1/attendance/me", headers=ht).json()["can_punch"] is True
    assert client.get("/api/v1/attendance/me", headers=ho).json()["can_punch"] is False
    r = client.post("/api/v1/attendance/my-punch", headers=ho, json={"latitude": CAIRO[0], "longitude": CAIRO[1]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "APP_PUNCH_OFF"

    now = local_now()
    morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
    _send(client, [f"21\t{morning:%Y-%m-%d %H:%M:%S}\t0\t1\n"], "PAYTEST0002")
    r = client.post("/api/v1/attendance/my-punch", headers=ht, json={"latitude": CAIRO[0], "longitude": CAIRO[1]})
    assert r.status_code == 201, r.text
    if now.hour < 13:      # the app punch is in the morning too: the installations manager is told, once
        inbox = client.get("/api/v1/notifications", headers=hm).json()["items"]
        assert sum("بصمتين" in n["title"] for n in inbox) == 1
        # the manager picks the app punch
        r = client.put(f"/api/v1/attendance/days/{e['id']}/{now.date().isoformat()}", headers=hm,
                       json={"start_source": "app"})
        assert r.status_code == 200, r.text
    pun = client.get(f"/api/v1/attendance/punches?date_from={now.date()}&date_to={now.date()}", headers=h).json()
    assert {p["pin"] for p in pun["items"]} == {"21"} and pun["total"] == 2


def test_commission_on_collections(platform, tenant_a, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "PAYC")
    h = tenant_a.h
    pol = client.post("/api/v1/pay-policies", headers=h, json={
        "code": "S2", "name": "مبيعات", "rules": {"commission_rate": "0.01", "commission_min_collections": "1000000"}})
    assert pol.status_code == 201, pol.text
    sp = _employee(client, h, branch, "مندوب", "31", pol.json(), 6000, department="sales")
    wo = _accepted_order(client, h, lib, branch, customer, "PAYC")
    wo = client.patch(f"/api/v1/work-orders/{wo['id']}", headers=h, json={"version": wo["version"], "salesperson_id": sp["id"]})
    assert wo.status_code == 200, wo.text
    wo = wo.json()
    box = client.post("/api/v1/cashboxes", headers=h, json={"code": "BPAYC", "name": "خزينة", "branch_id": branch["id"]}).json()
    r = client.post("/api/v1/cash-transactions", headers=h, json={
        "cashbox_id": box["id"], "direction": "in", "amount": "500", "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"]})
    assert r.status_code == 201, r.text
    from app.modules.hr.policy import local_now
    month = local_now().strftime("%Y-%m")
    run = client.post("/api/v1/payroll-runs", headers=h, json={"month": month, "branch_id": branch["id"]}).json()
    slip = next(s for s in run["payslips"] if s["employee_id"] == sp["id"])
    assert slip["collections"] == "500.00" and slip["commission"] == "0.00"      # under the minimum
    # the manager allows it this month
    run = client.post(f"/api/v1/payslips/{slip['id']}/commission", headers=h, json={"forced": True})
    assert run.status_code == 200, run.text
    slip = next(s for s in run.json()["payslips"] if s["employee_id"] == sp["id"])
    assert slip["commission"] == "5.00" and slip["commission_forced"] and slip["net"] == "6005.00"
