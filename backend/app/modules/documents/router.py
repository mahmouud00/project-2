"""GET .../print -> printable A4 HTML (the desktop app prints it or saves it as PDF)."""
from __future__ import annotations

import base64
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
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
    log_pii(db, ctx, "customer", [customer.id], "export", ["name", "phone", "address"])
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
    return _page("cutlist.html", db, ctx, title="كشف تقطيع", wo=wo, outputs=outputs,
                 customer=db.get(Customer, wo.customer_id))


class ReportSection(BaseModel):
    title: str = Field("", max_length=200)
    kv: list[tuple[str, str]] = Field(default_factory=list, max_length=200)
    columns: list[str] = Field(default_factory=list, max_length=30)
    rows: list[list[str]] = Field(default_factory=list, max_length=5000)
    nums: list[int] = Field(default_factory=list, max_length=30)


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
    sections = [{**s.model_dump(), "rows": [(r + [""] * len(s.columns))[:len(s.columns)] for r in s.rows]}
                for s in body.sections]
    return _page("report.html", db, ctx, title=body.title, subtitle=body.subtitle, landscape=landscape,
                 sections=sections)
