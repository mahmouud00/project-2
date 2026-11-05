"""سجل التغييرات لكل سجل: who changed what on a record, for whoever may read it."""
from tests.test_business_flow import _setup, price_at_top
from tests.test_org_permissions_locking import _make_user


def test_quotation_history_includes_its_lines_and_who(platform, tenant_a, tenant_b, client):
    lib, branch, _, customer = _setup(client, platform, tenant_a, "HIST")
    h = tenant_a.h
    line = {"model_id": lib["model"]["id"], "opening_width_mm": 1000, "opening_height_mm": 1000, "color_code": "W",
            "glass_material_code": "HIST-GLASS6"}
    q = client.post("/api/v1/quotations", headers=h, json={"customer_id": customer["id"], "branch_id": branch["id"],
                                                         "lines": [line]}).json()
    q = price_at_top(client, h, q)                     # the salesperson types the price on the line
    r = client.get(f"/api/v1/history/quotations/{q['id']}", headers=h)
    assert r.status_code == 200, r.text
    entries = r.json()
    assert any(e["entity"] == "quotations" and e["action"] == "create" for e in entries)
    priced = [e for e in entries if e["entity"] == "quotation_lines" and "manual_unit_price" in e["changes"]]
    assert priced and priced[0]["changes"]["manual_unit_price"]["new"] is not None
    assert all(e["user_name"] for e in entries)                     # who did it
    assert entries == sorted(entries, key=lambda e: e["at"], reverse=True)

    # the customer's personal data stays masked in the history
    c = client.get(f"/api/v1/history/customers/{customer['id']}", headers=h).json()
    assert c and c[-1]["changes"]["name"] == "***"

    # only for whoever may read the record, and only in their company
    assert client.get(f"/api/v1/history/quotations/{q['id']}", headers=tenant_b.h).status_code == 404
    client.post("/api/v1/roles", headers=h, json={"code": "hr_only", "name": "hr", "permissions": ["hr.read"]})
    _make_user(tenant_a, client, "hronly", "hr_only")
    r = client.get(f"/api/v1/history/quotations/{q['id']}", headers=tenant_a.headers("hronly", "user-pass-123"))
    assert r.status_code == 403
    assert client.get(f"/api/v1/history/unknown/{q['id']}", headers=h).status_code == 422
