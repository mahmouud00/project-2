"""Punches straight from the fingerprint device (ZKTeco ADMS push): registered devices only, each punch once,
matched to employees by their number on the device, and every company sees its own only."""
from app.modules.hr.attendance import parse_attlog

SN = "CQZ7240012345"


def _branch(client, h):
    return client.get("/api/v1/branches", headers=h).json()["items"][0]


def _employee(client, h, name, pin=None):
    body = {"full_name": name, "department": "production", "branch_id": _branch(client, h)["id"]}
    if pin is not None:
        body["attendance_pin"] = pin
    r = client.post("/api/v1/employees", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_parse_lines():
    rows = parse_attlog("1\t2026-11-12 08:01:22\t0\t1\t0\t0\t0\n"
                        "22 2026-11-12 17:05:00 1 15\n"
                        "bad line\n7\tnot a date\t0\n")
    assert [(r["pin"], str(r["punched_at"]), r["state"], r["verify"]) for r in rows] == [
        ("1", "2026-11-12 08:01:22", 0, 1), ("22", "2026-11-12 17:05:00", 1, 15)]


def test_device_pushes_punches(tenant_a, tenant_b, client):
    h = tenant_a.h
    ahmed = _employee(client, h, "أحمد", pin="1")

    # a device nobody added: answered, nothing kept
    assert client.get(f"/iclock/cdata?SN={SN}&options=all").text == "OK"
    r = client.post(f"/iclock/cdata?SN={SN}&table=ATTLOG", content="1\t2026-11-12 08:00:00\t0\t1\n")
    assert r.status_code == 200

    r = client.post("/api/v1/attendance/devices", headers=h, json={"serial": SN, "name": "بوابة المصنع"})
    assert r.status_code == 201, r.text
    dev = r.json()
    # the serial is this company's now: another company cannot take it
    r = client.post("/api/v1/attendance/devices", headers=tenant_b.h, json={"serial": SN})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEVICE_TAKEN"

    hello = client.get(f"/iclock/cdata?SN={SN}&options=all&pushver=2.4.1").text
    assert hello.startswith(f"GET OPTION FROM: {SN}") and "ATTLOGStamp=None" in hello

    body = ("1\t2026-11-12 08:01:22\t0\t1\t0\t0\t0\n"
            "1\t2026-11-12 17:02:10\t1\t1\t0\t0\t0\n"
            "9\t2026-11-12 08:30:00\t0\t15\t0\t0\t0\n")
    from app.modules.hr import attendance
    assert attendance.store_punches(attendance._device(SN), parse_attlog(body), "777") == 3
    assert attendance.store_punches(attendance._device(SN), parse_attlog(body), "777") == 0   # each once
    r = client.post(f"/iclock/cdata?SN={SN}&table=ATTLOG&Stamp=777", content=body)
    assert r.status_code == 200 and r.text == "OK: 3"
    # sent again (the network dropped before the device heard OK): kept once
    client.post(f"/iclock/cdata?SN={SN}&table=ATTLOG&Stamp=777", content=body)
    assert "ATTLOGStamp=777" in client.get(f"/iclock/cdata?SN={SN}&options=all").text
    assert client.get(f"/iclock/getrequest?SN={SN}").text == "OK"
    # what else the device sends (its users' names, photos) is not kept
    assert client.post(f"/iclock/cdata?SN={SN}&table=OPERLOG", content="USER PIN=1\tName=Ahmed\n").text == "OK"

    punches = client.get("/api/v1/attendance/punches?date_from=2026-11-12&date_to=2026-11-12", headers=h).json()
    assert punches["total"] == 3
    assert {(p["pin"], p["employee_name"]) for p in punches["items"]} == {("1", "أحمد"), ("9", None)}
    days = client.get("/api/v1/attendance/days?date_from=2026-11-12", headers=h).json()
    a = next(d for d in days if d["pin"] == "1")
    assert a["first"].endswith("08:01:22") and a["last"].endswith("17:02:10") and a["punches"] == 2
    assert client.get("/api/v1/attendance/unlinked", headers=h).json() == [
        {"pin": "9", "punches": 1, "last": "2026-11-12T08:30:00"}]

    # number 9 given to an employee later: the earlier punch becomes theirs
    sara = _employee(client, h, "سارة")
    r = client.patch(f"/api/v1/employees/{sara['id']}", headers=h, json={"version": sara["version"], "attendance_pin": "9"})
    assert r.status_code == 200 and r.json()["attendance_pin"] == "9"
    assert client.get("/api/v1/attendance/unlinked", headers=h).json() == []
    # two employees cannot have the same number
    r = client.patch(f"/api/v1/employees/{ahmed['id']}", headers=h, json={"version": ahmed["version"], "attendance_pin": "9"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PIN_TAKEN"

    devices = client.get("/api/v1/attendance/devices", headers=h).json()
    d = devices["devices"][0]
    assert d["punches"] == 3 and d["online"] and d["last_punch_at"].endswith("17:02:10") and "pushver=2.4.1" in d["info"]
    assert devices["server_port"] > 0

    # the other company sees nothing of it
    assert client.get("/api/v1/attendance/devices", headers=tenant_b.h).json()["devices"] == []
    assert client.get("/api/v1/attendance/punches?date_from=2026-11-12", headers=tenant_b.h).json()["total"] == 0

    # a stopped device: what it sends is no longer kept
    r = client.patch(f"/api/v1/attendance/devices/{dev['id']}", headers=h, json={"version": d["version"], "is_active": False})
    assert r.status_code == 200, r.text
    client.post(f"/iclock/cdata?SN={SN}&table=ATTLOG", content="1\t2026-11-13 08:00:00\t0\t1\n")
    assert client.get("/api/v1/attendance/punches?date_from=2026-11-13&date_to=2026-11-13", headers=h).json()["total"] == 0
