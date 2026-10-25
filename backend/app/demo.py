"""Demo environment for trying the system (python -m app.cli demo).

Creates, through the real API:
  - MYTech account  : company "__platform__", user vendor / Vendor@12345
  - customer company: company "DEMO", user admin / Admin@12345 (all modules, 1 year)
  - an EXAMPLE library system "DEMO-SL" (status: trial). Its numbers are
    illustrative only, NOT real deductions; delete or replace it with real systems.
  - price lists, warehouse with opening stock, cashbox, a customer, a survey and a quotation.
Idempotent: does nothing if the DEMO company already exists.
"""
from __future__ import annotations

import struct
import zlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

DEMO_CODE = "DEMO"
VENDOR = ("vendor", "Vendor@12345")
ADMIN = ("admin", "Admin@12345")


def _png(width: int = 160, height: int = 120) -> bytes:
    """Simple window icon (frame + 2 sashes) so the image endpoints have something to show."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            border = x < 6 or x >= width - 6 or y < 6 or y >= height - 6
            mid = width // 2 - 3 <= x <= width // 2 + 3
            sash = (12 <= x <= width - 13 and (y in (12, 13, height - 13, height - 14)
                                                  or x in (12, 13, width - 13, width - 14)))
            if border or mid or sash:
                row += bytes((70, 70, 80))
            else:
                row += bytes((190, 225, 245))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


DEFINITION = {
    "params": [{"name": "leaf_count", "label": "عدد الضلف", "type": "int", "default": 2, "min": 2, "max": 4},
               {"name": "with_screen", "label": "بسلك", "type": "bool", "default": True}],
    "formulas": [
        {"key": "frame_w", "label": "طول الحلق الأفقي", "expr": "width + 2 * weld_allowance"},
        {"key": "frame_h", "label": "طول الحلق الرأسي", "expr": "height + 2 * weld_allowance"},
        {"key": "sash_w", "label": "عرض الضلفة", "expr": "(width + sash_overlap_total) / leaf_count"},
        {"key": "sash_h", "label": "ارتفاع الضلفة", "expr": "height - sash_height_deduction"},
        {"key": "area", "label": "المساحة م²", "expr": "width * height / 10000", "unit": "area_m2"},
    ],
    "pieces": [
        {"key": "frame_top", "element": "حلق", "side": "width", "label": "حلق عرض", "role": "frame", "material_code": "DEMO-FRAME",
         "length_expr": "frame_w", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
        {"key": "frame_side", "element": "حلق", "side": "height", "label": "حلق ارتفاع", "role": "frame", "material_code": "DEMO-FRAME",
         "length_expr": "frame_h", "qty_expr": "2", "angle_left": "45", "angle_right": "45"},
        {"key": "sash_top", "element": "ضلفة", "side": "width", "label": "ضلفة عرض", "role": "sash", "material_code": "DEMO-SASH",
         "length_expr": "sash_w + 2 * weld_allowance", "qty_expr": "2 * leaf_count", "angle_left": "45",
         "angle_right": "45"},
        {"key": "sash_side", "element": "ضلفة", "side": "height", "label": "ضلفة ارتفاع", "role": "sash", "material_code": "DEMO-SASH",
         "length_expr": "sash_h + 2 * weld_allowance", "qty_expr": "2 * leaf_count", "angle_left": "45",
         "angle_right": "45"},
        {"key": "steel", "element": "حديد", "side": "width", "label": "حديد تدعيم الحلق", "role": "reinforcement", "material_code": "DEMO-STEEL",
         "length_expr": "width - 10", "qty_expr": "2"},
    ],
    "glass": [{"key": "pane", "label": "زجاج الضلفة", "width_expr": "sash_w - glass_deduction",
               "height_expr": "sash_h - glass_deduction", "qty_expr": "leaf_count"}],
    "accessories": [
        {"key": "handle", "label": "مقبض", "material_code": "DEMO-HANDLE", "qty_expr": "1"},
        {"key": "wheels", "label": "طقم عجل", "material_code": "DEMO-WHEEL", "qty_expr": "leaf_count"},
        {"key": "locks", "label": "سكاكة", "material_code": "DEMO-LOCK", "qty_expr": "2 * leaf_count"},
    ],
    "validations": [
        {"expr": "sash_w >= 30", "level": "error", "code": "SASH_TOO_NARROW", "message": "الضلفة أضيق من 30 سم"},
        {"expr": "width <= 400", "level": "warning", "code": "TOO_WIDE", "message": "عرض أكبر من 4 متر"},
    ],
    "drawing": [{"type": "frame", "x": "0", "y": "0", "w": "width", "h": "height"},
                {"type": "sash", "opening": "sliding_right", "x": "0", "y": "0", "w": "sash_w", "h": "sash_h"},
                {"type": "sash", "opening": "sliding_left", "x": "width - sash_w", "y": "0", "w": "sash_w",
                 "h": "sash_h"}],
}


# EXAMPLE half-circle arch (أرج) above a unit: its own frame. Width = the unit's width, height = total − height.
ARCH_DEFINITION = {
    "params": [],
    "formulas": [{"key": "curve", "label": "طول القوس", "expr": "arc_length(width, height)"}],
    "pieces": [
        {"key": "arch_curve", "element": "حلق الأرج", "label": "حلق مقوس", "role": "frame", "material_code": "DEMO-FRAME",
         "length_expr": "curve + 2 * weld_allowance", "qty_expr": "1", "angle_left": "90", "angle_right": "90"},
        {"key": "arch_base", "element": "حلق الأرج", "side": "width", "label": "قاعدة الأرج", "role": "frame",
         "material_code": "DEMO-FRAME", "length_expr": "width + 2 * weld_allowance", "qty_expr": "1",
         "angle_left": "45", "angle_right": "45"},
    ],
    "glass": [{"key": "arch_glass", "label": "زجاج الأرج", "width_expr": "width - glass_deduction",
               "height_expr": "height - glass_deduction / 2",
               "area_expr": "segment_area(width - glass_deduction, height - glass_deduction / 2)", "qty_expr": "1"}],
    "accessories": [], "validations": [], "drawing": [{"type": "frame", "x": "0", "y": "0", "w": "width", "h": "height"}],
}


def _ok(r, expected=(200, 201)):
    if r.status_code not in expected:
        raise RuntimeError(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text}")
    return r.json() if r.content else None


def setup_demo() -> bool:
    from fastapi.testclient import TestClient

    from app.db import models  # noqa: F401
    from app.db.base import PLATFORM_COMPANY_ID
    from app.db.session import system_session
    from app.licensing.models import Subscription
    from app.licensing.provider import MODULES
    from app.main import create_app
    from app.modules.org.models import Company, User
    from app.modules.org.service import create_company, create_platform_admin, ensure_platform_company

    with system_session() as db:
        if db.scalar(select(Company).where(Company.code == DEMO_CODE)):
            return False
        ensure_platform_company(db)
        if not db.scalar(select(User).where(User.company_id == PLATFORM_COMPANY_ID, User.username == VENDOR[0])):
            create_platform_admin(db, *VENDOR)
        company, admin = create_company(db, code=DEMO_CODE, name="مصنع تجريبي", admin_username=ADMIN[0],
                                        admin_password=ADMIN[1], admin_full_name="مدير المصنع")
        admin.must_change_password = False
        now = datetime.now(timezone.utc)
        db.add(Subscription(company_id=company.id, modules=list(MODULES), max_users=50, max_branches=10,
                            max_devices=50, starts_at=now, expires_at=now + timedelta(days=365)))
        db.commit()

    client = TestClient(create_app())

    def login(code, user):
        tok = _ok(client.post("/api/v1/auth/login", json={"company_code": code, "username": user[0],
                                                           "password": user[1], "device_key": "demo-setup"}))
        return {"Authorization": f"Bearer {tok['access_token']}"}

    # ---------------- MYTech builds the EXAMPLE library system
    v = login("__platform__", VENDOR)
    img = _ok(client.post("/api/v1/library/media", headers=v, files={"file": ("window.png", _png(), "image/png")}))
    for code, name, hexv in (("W", "أبيض", "#FFFFFF"), ("B", "بيج", "#E8DCC0")):
        _ok(client.post("/api/v1/library/colors", headers=v, json={"code": code, "name": name, "hex": hexv}))
    system = _ok(client.post("/api/v1/library/systems", headers=v, json={
        "code": "DEMO-SL", "name": "مثال تجريبي: جرار (أرقام غير حقيقية)", "supplier": "مثال",
        "material_type": "upvc", "unit": "cm", "rounding_step_mm": "0.5", "status": "trial", "image_id": img["id"],
        "description": "سيستم للتجربة فقط. الثوابت والمعادلات مجرد مثال وليست تخصيمات حقيقية."}))
    sid = system["id"]
    for c in _ok(client.get(f"/api/v1/library/systems/{sid}/constants", headers=v)):
        _ok(client.patch(f"/api/v1/library/constants/{c['id']}", headers=v, json={"version": c["version"], "value": "1"}))
    for name, label, value in (("weld_allowance", "سماحية اللحام", "0.3"),
                               ("sash_overlap_total", "ركوب الضلف (إجمالي)", "8.2"),
                               ("sash_height_deduction", "خصم ارتفاع الضلفة", "7.5"),
                               ("glass_deduction", "خصم الزجاج من الضلفة", "13")):
        _ok(client.post(f"/api/v1/library/systems/{sid}/constants", headers=v,
                        json={"name": name, "label": label, "value": value, "unit": "cm"}))
    materials = [
        ("DEMO-FRAME", "حلق جرار (مثال)", "profile", "m", "6000", "200", "110"),
        ("DEMO-SASH", "ضلفة جرار (مثال)", "profile", "m", "6000", "200", "95"),
        ("DEMO-STEEL", "حديد تدعيم (مثال)", "reinforcement", "m", "6000", "200", "40"),
        ("DEMO-HANDLE", "مقبض جرار (مثال)", "accessory", "pcs", None, None, "85"),
        ("DEMO-WHEEL", "طقم عجل (مثال)", "accessory", "set", None, None, "60"),
        ("DEMO-LOCK", "سكاكة (مثال)", "accessory", "pcs", None, None, "25"),
    ]
    for code, name, kind, unit, bar, min_piece, cost in materials:
        variants = [] if kind == "reinforcement" else [{"color_code": "W", "sku": f"{code}-W", "name": "أبيض"},
                                                       {"color_code": "B", "sku": f"{code}-B", "name": "بيج"}]
        _ok(client.post("/api/v1/library/materials", headers=v, json={
            "system_id": sid, "code": code, "name": name, "kind": kind, "unit": unit, "bar_length_mm": bar,
            "min_piece_mm": min_piece, "reference_cost": cost, "variants": variants}))
    _ok(client.post("/api/v1/library/materials", headers=v, json={
        "code": "DEMO-GLASS6", "name": "زجاج شفاف 6 مم (مثال)", "kind": "glass", "unit": "m2", "reference_cost": "350"}))
    model = _ok(client.post("/api/v1/library/models", headers=v, json={
        "system_id": sid, "code": "SL2", "name": "شباك جرار (مثال)", "category": "window", "status": "trial",
        "image_id": img["id"], "definition": DEFINITION}))
    preview = _ok(client.post(f"/api/v1/library/models/{model['id']}/preview", headers=v, json={
        "model_id": model["id"], "opening_width_mm": 1500, "opening_height_mm": 1200, "params": {"leaf_count": 2}}))
    _ok(client.post(f"/api/v1/library/models/{model['id']}/tests", headers=v, json={
        "name": "مثال 150×120 ضلفتين", "opening_width_mm": "1500", "opening_height_mm": "1200",
        "params": {"leaf_count": 2},
        "expected": {"pieces": {p["key"]: p["length_mm"] for p in preview["pieces"]}}}))
    arch = _ok(client.post("/api/v1/library/models", headers=v, json={
        "system_id": sid, "code": "AR1", "name": "أرج نص دايرة (مثال)", "category": "window", "status": "trial",
        "definition": ARCH_DEFINITION}))
    _ok(client.post(f"/api/v1/library/systems/{sid}/publish", headers=v, json={"notes": "نسخة تجريبية"}))

    # ---------------- the factory sets itself up
    a = login(DEMO_CODE, ADMIN)
    company = _ok(client.get("/api/v1/company", headers=a))
    _ok(client.patch("/api/v1/company", headers=a, json={"version": company["version"], "settings": {
        "display_name": "مصنع النور للشبابيك (تجريبي)", "phone": "0223456789", "phone2": "01000000000",
        "address": "المنطقة الصناعية - القاهرة", "tax_number": "000-000-000", "commercial_register": "00000",
        "invoice_footer": "شكرًا لثقتكم · الضمان 5 سنوات على القطاعات", "accent_color": "#5048E5",
        "default_tax_pct": "14", "deposit_pct": "30", "quote_waste_pct": "10", "saw_kerf_mm": "4",
        "bar_trim_mm": "10", "min_reusable_offcut_mm": "500", "quote_validity_days": 15,
        "quote_terms": "الأسعار سارية 15 يوم. التسليم خلال 21 يوم من دفع العربون.",
        "default_arch_model_id": arch["id"]}}))
    _ok(client.post("/api/v1/company/logo", headers=a, files={"file": ("logo.png", _png(240, 160), "image/png")}))
    branch = _ok(client.get("/api/v1/branches", headers=a))["items"][0]
    for code, name, ctype, margin in (("END", "عميل نهائي", "end", "30"), ("DEALER", "تاجر", "dealer", "15"),
                                      ("CONTRACTOR", "مقاول", "contractor", "20")):
        _ok(client.post("/api/v1/price-lists", headers=a, json={"code": code, "name": name, "customer_type": ctype,
                                                                "margin_pct": margin, "labor_cost_per_m2": "150"}))
    wh = _ok(client.post("/api/v1/warehouses", headers=a, json={"code": "MAIN", "name": "المخزن الرئيسي",
                                                                "branch_id": branch["id"]}))
    lines = [{"sku": f"{c}-{col}", "qty": "120" if u == "m" else "200", "unit_cost": cost}
             for c, _, kind, u, _, _, cost in materials if kind != "reinforcement" for col in ("W", "B")]
    lines.append({"sku": "DEMO-STEEL", "qty": "120", "unit_cost": "40"})
    _ok(client.post("/api/v1/inventory/adjustments", headers=a, json={
        "warehouse_id": wh["id"], "reason": "رصيد افتتاحي تجريبي", "lines": lines}))
    _ok(client.post("/api/v1/cashboxes", headers=a, json={"code": "MAIN", "name": "الخزينة الرئيسية",
                                                          "branch_id": branch["id"]}))
    _ok(client.post("/api/v1/suppliers", headers=a, json={"name": "مورد قطاعات (مثال)"}))
    customer = _ok(client.post("/api/v1/customers", headers=a, json={
        "name": "عميل تجريبي", "phone": "01000000000", "address": "عنوان تجريبي"}))
    survey = _ok(client.post("/api/v1/surveys", headers=a, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "address": "عنوان تجريبي", "openings": [
            {"location": "صالة", "opening_width_mm": 1800, "opening_height_mm": 1400, "qty": 2, "model_id": model["id"],
             "params": {"leaf_count": 2}, "color_code": "W", "glass_material_code": "DEMO-GLASS6"},
            {"location": "مطبخ", "opening_width_mm": 1200, "opening_height_mm": 1000, "model_id": model["id"],
             "params": {"leaf_count": 2}, "color_code": "B", "glass_material_code": "DEMO-GLASS6"}]}))
    quote = _ok(client.post("/api/v1/quotations", headers=a, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "survey_id": survey["id"], "discount_amount": "250"}))
    # a second, accepted quotation with its work order, deposit and an issued invoice
    q2 = _ok(client.post("/api/v1/quotations", headers=a, json={
        "customer_id": customer["id"], "branch_id": branch["id"], "survey_id": survey["id"]}))
    q2 = _ok(client.post(f"/api/v1/quotations/{q2['id']}/status", headers=a,
                         json={"version": q2["version"], "status": "accepted"}))
    wo = _ok(client.post("/api/v1/work-orders/from-quotation", headers=a, json={"quotation_id": q2["id"]}))
    box = _ok(client.get("/api/v1/cashboxes", headers=a))[0]
    _ok(client.post("/api/v1/cash-transactions", headers=a, json={
        "cashbox_id": box["id"], "direction": "in", "amount": wo["deposit_required"], "party_type": "customer",
        "party_id": customer["id"], "work_order_id": wo["id"], "note": "عربون"}))
    inv = _ok(client.post("/api/v1/invoices", headers=a, json={"work_order_id": wo["id"]}))
    inv = _ok(client.post(f"/api/v1/invoices/{inv['id']}/lines", headers=a, json={
        "kind": "service", "description": "تركيب ونقل", "qty": "1", "unit_price": "600"}))
    _ok(client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=a, json={"version": inv["version"]}))
    return True
