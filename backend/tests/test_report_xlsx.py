"""Any table exported to Excel: what the screen shows, numbers as numbers, never a formula."""
import io
from decimal import Decimal

from openpyxl import load_workbook


def test_report_as_excel(tenant_a, client):
    body = {"title": "العملاء", "subtitle": "الفرع الرئيسي", "sections": [{
        "title": "قائمة العملاء", "columns": ["الاسم", "الرصيد"], "nums": [1],
        "rows": [["أحمد", "1,250.50"], ["=HYPERLINK(\"http://x\")", "—"], ["@cmd", "12%"]]}]}
    r = client.post("/api/v1/documents/report.xlsx", headers=tenant_a.h, json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    ws = load_workbook(io.BytesIO(r.content)).worksheets[0]
    assert ws.title == "قائمة العملاء" and ws.sheet_view.rightToLeft
    values = [[c.value for c in row] for row in ws.iter_rows()]
    header = values.index(["الاسم", "الرصيد"])
    assert values[header + 1] == ["أحمد", Decimal("1250.50")] or values[header + 1] == ["أحمد", 1250.5]
    formula_row = ws.cell(header + 3, 1)                                     # sheet rows count from 1
    assert formula_row.data_type == "s" and formula_row.value.startswith("=")   # text, not a formula
    assert values[header + 3][1] in (Decimal("12"), 12)


def test_excel_export_needs_login(client):
    assert client.post("/api/v1/documents/report.xlsx", json={"title": "x", "sections": []}).status_code == 401


def test_report_pictures_are_inline_images_only(tenant_a, client):
    png = "data:image/png;base64,iVBORw0KGgo="
    body = {"title": "بنود", "sections": [{"title": "", "columns": ["الشكل", "السعر"], "rows": [["شباك", "10"], ["باب", "20"]],
            "pics": [[[png, "https://evil.example/x.png", "javascript:alert(1)"], []], [["data:text/html;base64,PHA+"], []]]}]}
    r = client.post("/api/v1/documents/report", headers=tenant_a.h, json=body)
    assert r.status_code == 200, r.text
    assert png in r.text and "evil.example" not in r.text and "javascript:" not in r.text and "data:text/html" not in r.text
