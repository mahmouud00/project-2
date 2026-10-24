def test_demo_setup_runs_and_is_idempotent(monkeypatch, client):
    import app.demo as demo

    monkeypatch.setattr(demo, "VENDOR", ("demo_vendor", "Vendor@12345"))
    assert demo.setup_demo() is True
    assert demo.setup_demo() is False
    tok = client.post("/api/v1/auth/token", data={"username": "admin", "password": "Admin@12345",
                                                  "client_id": "DEMO"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    q = client.get("/api/v1/quotations", headers=h).json()["items"]
    assert len(q) == 2 and all(float(x["total"]) > 0 for x in q)
    inv = client.get("/api/v1/invoices", headers=h).json()["items"]
    assert len(inv) == 1 and inv[0]["status"] == "issued" and inv[0]["number"]
    page = client.get(f"/api/v1/invoices/{inv[0]['id']}/print", headers=h)
    assert page.status_code == 200 and "<svg" in page.text
