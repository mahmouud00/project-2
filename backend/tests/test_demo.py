def test_demo_setup_runs_and_is_idempotent(monkeypatch, client):
    import app.demo as demo

    monkeypatch.setattr(demo, "VENDOR", ("demo_vendor", "Vendor@12345"))
    assert demo.setup_demo() is True
    assert demo.setup_demo() is False
    tok = client.post("/api/v1/auth/token", data={"username": "admin", "password": "Admin@12345",
                                                  "client_id": "DEMO"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    q = client.get("/api/v1/quotations", headers=h).json()["items"]
    assert len(q) == 1 and float(q[0]["total"]) > 0
