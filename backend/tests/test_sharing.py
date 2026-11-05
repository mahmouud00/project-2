"""A quotation shared with the customer by a link (e.g. WhatsApp): they read it, approve it or ask for a change."""
from tests.test_business_flow import _setup, price_at_top

UA = {"user-agent": "Mozilla/5.0 (Linux; Android 14) Mobile"}


def _quote(client, h, lib, branch, customer, code, priced=True):
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": f"{code}-GLASS6"}
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    return price_at_top(client, h, q) if priced else q


def _token(url: str) -> str:
    assert "/s/" in url
    return url.rsplit("/s/", 1)[1]


def test_customer_reads_and_answers_a_shared_quotation(platform, tenant_a, tenant_b, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "SHR")
    h = tenant_a.h
    unpriced = _quote(client, h, lib, branch, customer, "SHR", priced=False)
    r = client.post(f"/api/v1/quotations/{unpriced['id']}/share", headers=h, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUOTE_UNPRICED"

    q = _quote(client, h, lib, branch, customer, "SHR")
    r = client.post(f"/api/v1/quotations/{q['id']}/share", headers=h, json={"days": 7})
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["active"] and link["customer_phone"] == customer["phone"] and link["reachable_outside"] is False
    token = _token(link["url"])
    assert client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()["status"] == "sent"   # sharing is sending

    # a link preview is not the customer
    page = client.get(f"/s/{token}", headers={"user-agent": "WhatsApp/2.23.20.0"})
    assert page.status_code == 200 and q["number"] in page.text
    assert client.get(f"/api/v1/quotations/{q['id']}/share", headers=h).json()["views"] == 0
    page = client.get(f"/s/{token}", headers=UA)
    assert "موافق على العرض" in page.text and "noindex" in page.text
    seen = client.get(f"/api/v1/quotations/{q['id']}/share", headers=h).json()
    assert seen["views"] == 1 and seen["viewed_at"]
    assert seen["url"] is None                          # the token is never given back after the link is made

    # asking for a change keeps the quotation sent
    r = client.post(f"/s/{token}/change", data={"note": "عايز اللون بيج"}, headers=UA, follow_redirects=False)
    assert r.status_code == 303
    state = client.get(f"/api/v1/quotations/{q['id']}/share", headers=h).json()
    assert state["response"] == "change_requested" and state["response_note"] == "عايز اللون بيج"
    assert "اتبعت طلب التعديل" in client.get(f"/s/{token}", headers=UA).text
    assert client.post(f"/s/{token}/accept", headers=UA, follow_redirects=False).status_code == 303   # answered once
    assert client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()["status"] == "sent"

    # a new link (sent again): the older message's link keeps working; approving accepts the quotation
    token2 = _token(client.post(f"/api/v1/quotations/{q['id']}/share", headers=h, json={}).json()["url"])
    assert client.get(f"/s/{token}", headers=UA).status_code == 200
    assert client.post(f"/s/{token2}/accept", headers=UA, follow_redirects=False).status_code == 303
    assert client.get(f"/api/v1/quotations/{q['id']}", headers=h).json()["status"] == "accepted"
    assert "اتسجلت موافقتك" in client.get(f"/s/{token2}", headers=UA).text

    # cancelled, unknown, another company
    share_id = client.get(f"/api/v1/quotations/{q['id']}/share", headers=h).json()["id"]
    assert client.post(f"/api/v1/shares/{share_id}/revoke", headers=h).status_code == 200
    assert client.get(f"/s/{token2}", headers=UA).status_code == 410
    assert client.get(f"/s/{token}", headers=UA).status_code == 410              # cancelling cancels every link
    assert client.get("/s/not-a-real-token", headers=UA).status_code == 404
    assert client.get(f"/api/v1/quotations/{q['id']}/share", headers=tenant_b.h).status_code == 404


def test_invoice_link_needs_an_issued_invoice(tenant_a, client):
    h = tenant_a.h
    customer = client.post("/api/v1/customers", headers=h, json={"name": "عميل فاتورة"}).json()
    branch = client.get("/api/v1/branches", headers=h).json()["items"][0]
    inv = client.post("/api/v1/invoices", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [{"kind": "service", "description": "تركيب", "qty": "1", "unit_price": "50"}]}).json()
    r = client.post(f"/api/v1/invoices/{inv['id']}/share", headers=h, json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVOICE_NOT_ISSUED"
