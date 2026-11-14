"""GET .../print -> printable A4 HTML (the desktop app prints it or saves it as PDF)."""
from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.pii import log_pii
from app.modules.crm.models import Customer
from app.modules.crm.router import get_or_404
from app.modules.documents.render import company_context, data_uri, render
from app.modules.library.models import Color, ProductModel
from app.modules.library.service import find_material, model_image
from app.tenancy.context import get_db_and_ctx, require

router = APIRouter(tags=["documents"])
_FONTS = Path(__file__).with_name("fonts")


def _fonts_css() -> str:
    faces = []
    for f in sorted(_FONTS.glob("cairo-*.woff2")):
        b64 = base64.b64encode(f.read_bytes()).decode()
        faces.append(f"@font-face{{font-family:'Cairo';font-weight:200 1000;src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    return "\n".join(faces)


def _area(x) -> str:
    return format(Decimal(str(x)).quantize(Decimal("0.01")), "f")


def _num(x) -> str:
    d = Decimal(str(x)).normalize()
    return format(d, "f")


class _Lookups:
    def __init__(self, db):
        self.db = db
        self.colors = {c.code: c.name for c in db.scalars(select(Color))}
        self.images: dict = {}

    def image(self, media_id):
        if media_id not in self.images:
            self.images[media_id] = data_uri(self.db, media_id)
        return self.images[media_id]

    def glass(self, code):
        if not code:
            return ""
        m = find_material(self.db, code)
        return m.name if m else code

    def params(self, model_id, values: dict) -> list[str]:
        model = self.db.get(ProductModel, model_id) if model_id else None
        if model is None:
            return []
        out = []
        for p in model.definition.get("params", []):
            if p["name"] not in values:
                continue
            v = values[p["name"]]
            if p.get("type") == "bool":
                if v in (True, "true", 1, "1"):
                    out.append(p.get("label") or p["name"])
                continue
            if p.get("type") == "choice":
                label = next((c["label"] for c in p.get("choices", []) if Decimal(str(c["value"])) == Decimal(str(v))), v)
                out.append(f"{p.get('label') or p['name']}: {label}")
            else:
                out.append(f"{p.get('label') or p['name']}: {v}")
        return out


def _page(template: str, db, ctx, **kw) -> HTMLResponse:
    html = render(template, company=company_context(db, ctx.company_id), fonts_css=_fonts_css(),
                  printed_at=datetime.now().strftime("%Y-%m-%d %H:%M"), **kw)
    return HTMLResponse(html)


@router.get("/invoices/{inv_id}/print", response_class=HTMLResponse)
def print_invoice(inv_id: uuid.UUID, dc=Depends(require("treasury.read"))):
    from app.modules.invoicing.models import Invoice
    from app.modules.invoicing.router import _lines, invoice_out
    from app.modules.production.models import WorkOrder
    from app.modules.sales.models import Quotation

    db, ctx = dc
    inv = get_or_404(db, Invoice, inv_id)
    ctx.require("treasury.read", inv.branch_id)
    out = invoice_out(db, inv)
    look = _Lookups(db)
    lines = []
    for l in _lines(db, inv):
        lines.append({**{c: getattr(l, c) for c in ("description", "model_name", "location", "opening_width_mm",
                                                     "opening_height_mm", "width_mm", "height_mm", "drawing",
                                                     "unit_price", "discount_amount", "line_total")},
                      "qty_text": _num(l.qty), "discount_pct_text": _num(l.discount_pct),
                      "image": look.image(l.model_image_id), "color_name": look.colors.get(l.color_code or "", l.color_code),
                      "glass_name": look.glass(l.glass_material_code), "param_labels": look.params(l.model_id, l.params)})
    customer = db.get(Customer, inv.customer_id)
    log_pii(db, ctx, "customer", [customer.id], "export", ["name", "phone", "address"])
    db.commit()
    title = "فاتورة" if inv.status != "draft" else "فاتورة (مسودة)"
    return _page("invoice.html", db, ctx, title=title, doc=inv, lines=lines, customer=customer,
                 work_order=db.get(WorkOrder, inv.work_order_id) if inv.work_order_id else None,
                 quotation=db.get(Quotation, inv.quotation_id) if inv.quotation_id else None,
                 paid=out.paid_amount, balance=out.balance, tax_pct_text=_num(inv.tax_pct))


@router.get("/quotations/{quote_id}/print", response_class=HTMLResponse)
def print_quotation(quote_id: uuid.UUID, dc=Depends(require("quotes.read"))):
    from app.modules.org.settings import get_company_settings
    from app.modules.sales.models import Quotation, QuotationLine
    from app.modules.sales.pricing import money

    db, ctx = dc
    q = get_or_404(db, Quotation, quote_id)
    ctx.require("quotes.read", q.branch_id)
    look = _Lookups(db)
    lines, total_area = [], Decimal(0)
    for l in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id)
                        .order_by(QuotationLine.position, QuotationLine.parent_line_id.is_not(None))):
        model = db.get(ProductModel, l.model_id)
        inputs = (l.calc or {}).get("inputs", {})
        if l.parent_line_id is not None and lines:      # the unit's arch: shown with its unit, priced in it
            lines[-1]["arch"] = {"model_code": model.code if model else "", "model_name": model.name if model else "",
                                 "width_mm": l.opening_width_mm, "height_mm": l.opening_height_mm,
                                 "drawing": (l.calc or {}).get("drawing", [])}
            continue
        billed = l.billed_area_m2 or l.area_m2
        ppm = l.price_per_m2 if l.price_per_m2 is not None else (money(l.unit_price / billed) if billed else None)
        total_area += billed * l.qty
        lines.append({"model_name": model.name if model else "", "model_code": model.code if model else "",
                      "area": _area(l.area_m2), "billed_area": _area(billed), "total_area": _area(billed * l.qty),
                      "price_per_m2": ppm, "location": l.location,
                      "opening_width_mm": l.opening_width_mm, "opening_height_mm": l.opening_height_mm,
                      "total_height_mm": l.total_height_mm, "width_mm": inputs.get("width_mm"), "height_mm": inputs.get("height_mm"),
                      "drawing": (l.calc or {}).get("drawing", []), "qty": l.qty, "unit_price": l.unit_price,
                      "line_total": l.line_total, "image": look.image(model_image(model, l.color_code)),
                      "color_name": look.colors.get(l.color_code or "", l.color_code),
                      "glass_name": look.glass(l.glass_material_code), "param_labels": look.params(l.model_id, l.params)})
    customer = db.get(Customer, q.customer_id)
    log_pii(db, ctx, "customer", [customer.id], "export", ["name", "phone", "address"])
    db.commit()
    deposit = money(q.total * get_company_settings(db, ctx.company_id).deposit_pct / 100)
    return _page("quotation.html", db, ctx, title="عرض سعر", doc=q, lines=lines, customer=customer,
                 deposit=deposit if deposit else None, tax_pct_text=_num(q.tax_pct), total_area=_area(total_area))


@router.get("/surveys/{survey_id}/print", response_class=HTMLResponse)
def print_survey(survey_id: uuid.UUID, dc=Depends(require("surveys.read"))):
    """The survey sheet (landscape), the same columns as the paper form; at least 10 rows so an empty
    survey prints as a blank form for the technician."""
    from app.modules.crm.models import SiteSurvey, SurveyOpening

    db, ctx = dc
    survey = get_or_404(db, SiteSurvey, survey_id)
    ctx.require("surveys.read", survey.branch_id)
    look = _Lookups(db)
    rows = []
    for o in db.scalars(select(SurveyOpening).where(SurveyOpening.survey_id == survey.id).order_by(SurveyOpening.position)):
        model = db.get(ProductModel, o.model_id) if o.model_id else None
        rows.append({c: getattr(o, c) for c in ("position", "location", "opening_width_mm", "opening_height_mm",
                                                 "total_height_mm", "unit_kind", "glass_layers", "glass_color",
                                                 "screen_type", "application", "installation_method", "motor_type")}
                    | {"model_code": model.code if model else "",
                       "color": o.color_text or look.colors.get(o.color_code or "", o.color_code)})
    rows += [{}] * max(0, 10 - len(rows))
    customer = db.get(Customer, survey.customer_id)
    log_pii(db, ctx, "customer", [customer.id], "export", ["name", "phone", "address", "location"])
    db.commit()
    title = "معاينة شيش" if survey.kind == "shutter" else "معاينة"
    return _page("survey.html", db, ctx, title=title, doc=survey, rows=rows, customer=customer, landscape=True)


@router.get("/work-orders/{wo_id}/print/cut-list", response_class=HTMLResponse)
def print_cut_list(wo_id: uuid.UUID, dc=Depends(require("workorders.read"))):
    from app.modules.production.manufacturing import generate_outputs
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    wo = get_or_404(db, WorkOrder, wo_id)
    ctx.require("workorders.read", wo.branch_id)
    outputs = wo.outputs or generate_outputs(db, wo)
    log_pii(db, ctx, "customer", [wo.customer_id], "export", ["name"])
    db.commit()
    return _page("cutlist.html", db, ctx, title="كشف تقطيع", wo=wo, outputs=outputs, landscape=True,
                 customer=db.get(Customer, wo.customer_id))


@router.get("/work-orders/{wo_id}/print/glass", response_class=HTMLResponse)
def print_glass_order(wo_id: uuid.UUID, dc=Depends(require("workorders.read"))):
    """طلبية الزجاج: the glass of the order only, grouped by glass type, with the total m² of each type."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.modules.library.models import Material
    from app.modules.production.manufacturing import generate_outputs, unit_ranges
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    wo = get_or_404(db, WorkOrder, wo_id)
    ctx.require("workorders.read", wo.branch_id)
    outputs = wo.outputs or generate_outputs(db, wo)
    rows = outputs.get("glass") or []
    codes = {g.get("material_code") for g in rows if g.get("material_code")}
    names = {}
    for m in db.scalars(select(Material).where(Material.code.in_(codes), Material.deleted_at.is_(None))):
        if m.company_id == ctx.company_id or m.code not in names:     # the company's own name first
            names[m.code] = m.name
    windows = {d.get("item"): unit_ranges(d.get("units") or []) for d in outputs.get("drawings") or []}
    types: dict = {}
    for g in rows:
        code = g.get("material_code") or ""
        t = types.setdefault(code, {"code": code, "name": names.get(code, ""), "rows": [], "qty": 0,
                                    "area": Decimal(0)})
        t["rows"].append({**g, "windows": windows.get(g.get("item"), "")})
        t["qty"] += int(g.get("qty") or 0)
        t["area"] += Decimal(str(g.get("area_m2") or 0))
    groups = sorted(types.values(), key=lambda t: (t["name"] or t["code"]))
    for t in groups:
        t["area"] = t["area"].quantize(Decimal("0.01"))
    total = sum((t["area"] for t in groups), Decimal(0))
    log_pii(db, ctx, "customer", [wo.customer_id], "export", ["name"])
    db.commit()
    return _page("glass.html", db, ctx, title="طلبية زجاج", wo=wo, groups=groups, total_area=total,
                 total_qty=sum(t["qty"] for t in groups), customer=db.get(Customer, wo.customer_id))


def _installation(db, ctx, wo, job=None) -> HTMLResponse:
    """أمر التركيب: every window on its own row (two of the same size are two rows), numbered as on the cut sheet,
    with where it goes, its model, sizes and specifications; a box to tick and the customer's signature."""
    from app.core.errors import Conflict
    from app.modules.org.models import User
    from app.modules.production.models import WorkOrderItem

    if wo.stage not in ("installation", "delivered"):     # it appears once the order is made
        raise Conflict("The installation order appears when the order reaches installation",
                       code="NOT_READY_FOR_INSTALLATION", details={"stage": wo.stage})
    look = _Lookups(db)
    units, no = [], 0
    for item in db.scalars(select(WorkOrderItem).where(WorkOrderItem.work_order_id == wo.id).order_by(WorkOrderItem.position)):
        model = db.get(ProductModel, item.model_id)
        inputs = (item.calc or {}).get("inputs", {})
        for k in range(item.qty):
            no += 1
            units.append({"no": no, "location": item.location, "of": f"{k + 1} من {item.qty}" if item.qty > 1 else "",
                          "model_name": model.name if model else "", "model_code": model.code if model else "",
                          "opening_width_mm": item.opening_width_mm, "opening_height_mm": item.opening_height_mm,
                          "width_mm": inputs.get("width_mm"), "height_mm": inputs.get("height_mm"),
                          "drawing": (item.calc or {}).get("drawing", []),
                          "color": look.colors.get(item.color_code or "", item.color_code),
                          "glass": look.glass(item.glass_material_code), "params": look.params(item.model_id, item.params),
                          "notes": getattr(item, "notes", "") or ""})
    customer = db.get(Customer, wo.customer_id)
    tech = db.get(User, job.technician_id) if job is not None else None
    from app.modules.documents.render import map_link
    place = map_link(job.location_url, job.latitude, job.longitude) if job is not None else ""
    log_pii(db, ctx, "customer", [customer.id], "export", ["name", "phone", "address", "location"])
    db.commit()
    return _page("installation.html", db, ctx, title="أمر تركيب", wo=wo, job=job, units=units, customer=customer,
                 technician=tech.full_name if tech else "", address=(job.address if job is not None else None),
                 place=place)


@router.get("/work-orders/{wo_id}/print/installation", response_class=HTMLResponse)
def print_installation(wo_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    wo = get_or_404(db, WorkOrder, wo_id)
    ctx.require("field.install_doc", wo.branch_id)
    return _installation(db, ctx, wo)


@router.get("/field/jobs/{job_id}/installation-order", response_class=HTMLResponse)
def print_job_installation(job_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    """The installation order of a technician's installation job: the office or the job's own technician."""
    from app.core.errors import Conflict
    from app.modules.field.router import _job
    from app.modules.production.models import WorkOrder

    db, ctx = dc
    job = _job(db, ctx, job_id)
    ctx.require("field.install_doc", job.branch_id)
    if job.work_order_id is None:
        raise Conflict("This job has no work order", code="NO_WORK_ORDER")
    return _installation(db, ctx, get_or_404(db, WorkOrder, job.work_order_id), job)


_PIC = re.compile(r"^data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$")


def _safe_pic(uri) -> bool:
    """A picture sent with a report: an inline image only (never a link), at most ~600 KB."""
    return isinstance(uri, str) and len(uri) <= 800_000 and bool(_PIC.match(uri))


class ReportSection(BaseModel):
    title: str = Field("", max_length=200)
    kv: list[tuple[str, str]] = Field(default_factory=list, max_length=200)
    columns: list[str] = Field(default_factory=list, max_length=30)
    rows: list[list[str]] = Field(default_factory=list, max_length=5000)
    nums: list[int] = Field(default_factory=list, max_length=30)
    # pictures in the cells (a model's photo, a window's drawing), same shape as rows: data:image URIs only
    pics: list[list[list[str]]] = Field(default_factory=list, max_length=5000)


class ReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field("", max_length=300)
    landscape: bool | None = None
    sections: list[ReportSection] = Field(max_length=30)


@router.post("/documents/report", response_class=HTMLResponse)
def print_report(body: ReportIn, dc=Depends(get_db_and_ctx)):
    """Any screen printed as an A4 document with the company's logo and details. The program sends what the
    user sees (headers and rows as text); nothing is read from the database except the company branding."""
    db, ctx = dc
    landscape = body.landscape if body.landscape is not None else any(len(s.columns) > 7 for s in body.sections)
    sections = [{**s.model_dump(), "rows": [(r + [""] * len(s.columns))[:len(s.columns)] for r in s.rows],
                 "pics": [[[u for u in cell if _safe_pic(u)][:3] for cell in row][:len(s.columns)]
                          for row in s.pics][:len(s.rows)]}
                for s in body.sections]
    return _page("report.html", db, ctx, title=body.title, subtitle=body.subtitle, landscape=landscape,
                 sections=sections)



@router.post("/documents/report.xlsx")
def export_report_xlsx(body: ReportIn, dc=Depends(get_db_and_ctx)):
    """The same report as an Excel workbook (a sheet per table, right to left). Like the printout it holds only what
    the user sees on the screen; numbers in numeric columns become real numbers, every other cell stays text
    (a value starting with = is never turned into a formula)."""
    import io
    import re
    from urllib.parse import quote

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    db, ctx = dc
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for n, sec in enumerate(body.sections or [ReportSection()], start=1):
        name = re.sub(r"[\\/*?:\[\]]", " ", sec.title or body.title).strip()[:28] or f"Sheet{n}"
        while name in used:
            name = f"{name[:25]} {n}"
        used.add(name)
        ws = wb.create_sheet(name)
        ws.sheet_view.rightToLeft = True
        r = 1
        ws.cell(r, 1, body.title).font = Font(bold=True, size=13)
        if body.subtitle:
            r += 1
            ws.cell(r, 1, body.subtitle).font = Font(color="666666")
        for k, v in sec.kv:
            r += 1
            ws.cell(r, 1, k).font = Font(bold=True)
            _text_cell(ws.cell(r, 2), v)
        if sec.columns:
            r += 2
            for c, label in enumerate(sec.columns, start=1):
                cell = ws.cell(r, c, label)
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="DDE7F7")
                cell.alignment = Alignment(horizontal="center")
            nums = set(sec.nums)
            for row in sec.rows:
                r += 1
                for c, v in enumerate(row[:len(sec.columns)], start=1):
                    number = _number(v) if (c - 1) in nums else None
                    if number is not None:
                        ws.cell(r, c, number)
                    else:
                        _text_cell(ws.cell(r, c), v)
            for c in range(1, len(sec.columns) + 1):
                width = max([len(str(sec.columns[c - 1]))] + [len(str(x[c - 1])) for x in sec.rows if len(x) >= c] or [8])
                ws.column_dimensions[ws.cell(1, c).column_letter].width = min(60, max(8, width + 2))
    buf = io.BytesIO()
    wb.save(buf)
    name = quote((body.title or "report")[:80] + ".xlsx")
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=report.xlsx; filename*=UTF-8''{name}"})


def _number(v: str) -> Decimal | None:
    text = str(v).replace(",", "").replace("٬", "").strip()
    for suffix in ("EGP", "ج.م", "%", "م²", "سم", "مم"):
        text = text.removesuffix(suffix).strip()
    try:
        return Decimal(text) if text and text not in ("-", "—") else None
    except Exception:
        return None


def _text_cell(cell, v) -> None:
    cell.value = "" if v is None else str(v)
    cell.data_type = "s"          # never a formula, whatever the text starts with