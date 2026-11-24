"""Chat between users (text, pictures, files; only members see a conversation), online / last seen, delegating
permissions for a while, the activity log with who did what, and the customer's WhatsApp number."""
from datetime import datetime, timedelta, timezone

from tests.test_org_permissions_locking import _make_user


def test_chat_between_users(tenant_a, tenant_b, client):
    a = _make_user(tenant_a, client, "chat-a", "sales")
    b = _make_user(tenant_a, client, "chat-b", "sales")
    _make_user(tenant_a, client, "chat-c", "sales")
    ha, hb = tenant_a.headers("chat-a", "user-pass-123"), tenant_a.headers("chat-b", "user-pass-123")
    hc = tenant_a.headers("chat-c", "user-pass-123")

    people = {p["username"]: p for p in client.get("/api/v1/chat/people", headers=ha).json()}
    assert people["chat-b"]["online"] is True and "chat-a" not in people        # just signed in; not myself
    conv = client.post(f"/api/v1/chat/direct/{b['id']}", headers=ha).json()
    assert client.post(f"/api/v1/chat/direct/{a['id']}", headers=hb).json()["id"] == conv["id"]   # the same one
    r = client.post(f"/api/v1/chat/conversations/{conv['id']}/messages", headers=ha, json={"body": "صباح الخير"})
    assert r.status_code == 201 and r.json()["mine"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    r = client.post(f"/api/v1/chat/conversations/{conv['id']}/files?caption=المقاس", headers=ha,
                    files={"file": ("plan.png", png, "image/png")})
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["file_name"] == "plan.png" and f["body"] == "المقاس"

    assert client.get("/api/v1/chat/unread", headers=hb).json()["unread"] == 2
    msgs = client.get(f"/api/v1/chat/conversations/{conv['id']}/messages", headers=hb).json()
    assert [m["body"] for m in msgs] == ["صباح الخير", "المقاس"] and not msgs[0]["mine"]
    assert client.get("/api/v1/chat/unread", headers=hb).json()["unread"] == 0          # read now
    assert client.get(f"/api/v1/chat/files/{f['id']}", headers=hb).content == png
    # someone else in the company: neither the conversation nor its file
    assert client.get(f"/api/v1/chat/conversations/{conv['id']}/messages", headers=hc).status_code == 404
    assert client.get(f"/api/v1/chat/files/{f['id']}", headers=hc).status_code == 404
    assert client.get(f"/api/v1/chat/files/{f['id']}", headers=tenant_b.h).status_code == 404
    # a notification reached the other person
    inbox = client.get("/api/v1/notifications", headers=hb).json()["items"]
    assert any("رسالة من" in n["title"] for n in inbox)
    # a group; only the sender takes a message back
    g = client.post("/api/v1/chat/groups", headers=ha, json={"title": "المبيعات", "user_ids": [b["id"]]}).json()
    m = client.post(f"/api/v1/chat/conversations/{g['id']}/messages", headers=ha, json={"body": "اجتماع"}).json()
    assert client.delete(f"/api/v1/chat/messages/{m['id']}", headers=hb).status_code == 403
    assert client.delete(f"/api/v1/chat/messages/{m['id']}", headers=ha).status_code == 204
    convs = {c["title"]: c for c in client.get("/api/v1/chat/conversations", headers=hb).json()}
    assert "المبيعات" in convs


def test_delegating_permissions(tenant_a, client):
    _make_user(tenant_a, client, "boss", "accounts")
    helper = _make_user(tenant_a, client, "helper", "sales")
    hboss, hhelp = tenant_a.headers("boss", "user-pass-123"), tenant_a.headers("helper", "user-pass-123")
    assert client.get("/api/v1/cashboxes", headers=hhelp).status_code == 403
    now = datetime.now(timezone.utc)
    r = client.post("/api/v1/delegations", headers=hboss, json={
        "to_user_id": helper["id"], "ends_at": (now + timedelta(days=3)).isoformat(), "note": "إجازة"})
    assert r.status_code == 201 and r.json()["active"], r.text
    d = r.json()
    assert client.get("/api/v1/cashboxes", headers=hhelp).status_code == 200     # the boss's permissions now
    assert [x["id"] for x in client.get("/api/v1/delegations", headers=hhelp).json()] == [d["id"]]
    assert client.post(f"/api/v1/delegations/{d['id']}/revoke", headers=hboss).json()["active"] is False
    assert client.get("/api/v1/cashboxes", headers=hhelp).status_code == 403
    # a later window is not active yet; the end before the start is refused
    later = client.post("/api/v1/delegations", headers=hboss, json={
        "to_user_id": helper["id"], "starts_at": (now + timedelta(days=1)).isoformat(),
        "ends_at": (now + timedelta(days=2)).isoformat()}).json()
    assert later["active"] is False and client.get("/api/v1/cashboxes", headers=hhelp).status_code == 403
    r = client.post("/api/v1/delegations", headers=hboss, json={
        "to_user_id": helper["id"], "starts_at": now.isoformat(), "ends_at": (now - timedelta(hours=1)).isoformat()})
    assert r.status_code == 422


def test_activity_log_names_who(tenant_a, client):
    u = _make_user(tenant_a, client, "logger", "sales")
    hl = tenant_a.headers("logger", "user-pass-123")
    r = client.post("/api/v1/customers", headers=hl, json={"name": "عميل السجل", "phone": "01000000000",
                                                         "whatsapp": "01111111111", "kind": "final"})
    assert r.status_code == 201, r.text
    assert r.json()["whatsapp"] == "01111111111"
    log = client.get(f"/api/v1/audit-log?user_id={u['id']}", headers=tenant_a.h).json()["items"]
    assert {e["action"] for e in log} >= {"login", "create"} and all(e["user_name"] for e in log)
    logins = client.get("/api/v1/audit-log?action=login", headers=tenant_a.h).json()["items"]
    assert logins and all(e["entity"] == "users" for e in logins)
