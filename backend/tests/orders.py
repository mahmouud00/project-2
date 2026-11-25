"""The way to a work order now: accepted quotation → issued invoice → the deposit collected on it and confirmed by
the accounts → «تحويل لأمر تصنيع»."""
import uuid


def cashbox(client, h, branch_id: str) -> dict:
    return client.post("/api/v1/cashboxes", headers=h, json={"code": f"T{uuid.uuid4().hex[:6]}", "name": "خزينة",
                                                             "branch_id": branch_id}).json()


def invoice_of(client, h, q: dict) -> dict:
    inv = client.post("/api/v1/invoices", headers=h, json={"quotation_id": q["id"]})
    assert inv.status_code == 201, inv.text
    inv = inv.json()
    r = client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=h, json={"version": inv["version"]})
    assert r.status_code == 200, r.text
    return r.json()


def collect(client, h, inv: dict, amount, box: dict | None = None, confirm_h=None) -> dict:
    """Record money on the invoice and have the accounts (confirm_h, default h) confirm it."""
    c = client.post(f"/api/v1/invoices/{inv['id']}/collections", headers=h, json={"amount": str(amount)})
    assert c.status_code == 201, c.text
    c = c.json()
    box = box or cashbox(client, confirm_h or h, inv["branch_id"])
    r = client.post(f"/api/v1/collections/{c['id']}/confirm", headers=confirm_h or h,
                    json={"version": c["version"], "cashbox_id": box["id"]})
    assert r.status_code == 200, r.text
    return r.json()


def order(client, h, q: dict, *, deposit=True, due_date=None) -> dict:
    """Work order of an accepted quotation, through its invoice (the deposit collected and confirmed)."""
    inv = invoice_of(client, h, q)
    if deposit and float(inv["deposit_amount"]) > 0:
        collect(client, h, inv, inv["deposit_amount"])
        inv = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    r = client.post(f"/api/v1/invoices/{inv['id']}/work-order", headers=h,
                    json={"version": inv["version"], "due_date": due_date})
    assert r.status_code == 200, r.text
    return r.json()
