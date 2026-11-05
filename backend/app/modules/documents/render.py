"""Printable documents (A4 HTML): invoices, quotations, cut lists.

Self-contained HTML (logo and model images embedded as data URIs, fonts
bundled by the desktop app or the system), so the desktop program can print
or save as PDF without internet. Every document carries the company's name,
logo and details. Sizes are shown in cm, width before height.
"""
from __future__ import annotations

import base64
import uuid
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Undefined, select_autoescape
from markupsafe import Markup

from app.modules.library.models import MediaFile

TEMPLATES = Path(__file__).with_name("templates")
env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def cm(mm) -> str:
    if mm is None or mm == "" or isinstance(mm, Undefined):
        return ""
    value = (Decimal(str(mm)) / 10).quantize(Decimal("0.01")).normalize()
    return format(value, "f")


def money(x) -> str:
    return f"{Decimal(str(x or 0)):,.2f}"


def size(w_mm, h_mm) -> Markup:
    """Width first (on the right in Arabic reading order)."""
    if w_mm is None or h_mm is None:
        return Markup("")
    return Markup(f'<span class="dim"><b>{cm(w_mm)}</b><span class="x">×</span>{cm(h_mm)}</span>')


def map_link(url=None, lat=None, lng=None) -> str:
    """Link that opens the place: the coordinates when known, else the link as the customer sent it."""
    if lat is not None and lng is not None and not isinstance(lat, Undefined):
        return f"https://www.google.com/maps?q={lat},{lng}"
    return url or ""


def qr(text: str, size_mm: int = 22) -> Markup:
    """QR code (inline SVG) the technician scans with the phone to open the place on the map."""
    if not text:
        return Markup("")
    import segno

    svg = segno.make(text, error="m").svg_inline(scale=1, border=1, dark="#1B2533")
    return Markup(svg.replace("<svg ", f'<svg style="width:{size_mm}mm;height:{size_mm}mm" ', 1))


env.filters.update(cm=cm, money=money)
env.globals.update(size=size, map_link=map_link, qr=qr)


def data_uri(db, media_id) -> str | None:
    from app.modules.library.router import media_path

    if not media_id:
        return None
    media = db.get(MediaFile, uuid.UUID(str(media_id)))
    if media is None or not media_path(media.sha256).exists():
        return None
    return f"data:{media.mime};base64," + base64.b64encode(media_path(media.sha256).read_bytes()).decode()


def drawing_svg(elements: list, width_mm=None, height_mm=None, max_w: int = 150, max_h: int = 120, dims: bool = True,
                label_w=None, label_h=None) -> Markup:
    """The window drawn from the engine's drawing elements (frame / sash / glass / panel / mullion) with its opening
    marks, and its width (above) and height (beside it) in cm when both are known. The shape is at manufacturing
    size; `label_w` / `label_h` say which size the numbers show (a quotation shows the opening the customer ordered)."""
    elements = elements or []
    if not elements and not (width_mm and height_mm):
        return Markup("")
    fw = Decimal(str(width_mm or max((Decimal(str(e.get("w_mm", 0))) for e in elements), default=1)))
    fh = Decimal(str(height_mm or max((Decimal(str(e.get("h_mm", 0))) for e in elements), default=1)))
    show = bool(dims and width_mm and height_mm)
    mx, my = (22, 16) if show else (4, 4)                 # room for the height on the left, the width on top
    scale = min(Decimal(max_w - mx - 4) / fw, Decimal(max_h - my - 4) / fh)
    W, H = float(fw * scale), float(fh * scale)
    parts = [f'<rect x="{mx}" y="{my}" width="{W:.1f}" height="{H:.1f}" fill="#F8FAFC" stroke="#334155" stroke-width="1.4"/>']
    for e in elements:
        x = mx + float(Decimal(str(e.get("x_mm", 0))) * scale)
        y = my + float(Decimal(str(e.get("y_mm", 0))) * scale)
        w = float(Decimal(str(e.get("w_mm", 0))) * scale)
        h = float(Decimal(str(e.get("h_mm", 0))) * scale)
        kind = e.get("type", "rect")
        if kind == "frame":
            continue
        inset = 3 if kind == "sash" else 0
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#fff" stroke="#475569"/>')
        if kind in ("sash", "glass", "rect", "panel"):
            fill = "#D7ECFA" if kind != "panel" else "#E5E7EB"
            parts.append(f'<rect x="{x + inset:.1f}" y="{y + inset:.1f}" width="{max(w - 2 * inset, 1):.1f}" '
                         f'height="{max(h - 2 * inset, 1):.1f}" fill="{fill}" stroke="#64748B" stroke-width=".7"/>')
        opening = (e.get("opening") or "").lower()
        cx, cy = x + w / 2, y + h / 2
        if opening.startswith("sliding"):
            d = 1 if opening.endswith("right") else -1
            parts.append(f'<path d="M{cx - 8 * d:.1f} {cy:.1f} h{16 * d} m{-4 * d} -3 l{4 * d} 3 l{-4 * d} 3" '
                         f'stroke="#4338CA" stroke-width="1.2" fill="none"/>')
        elif opening.startswith("casement") or opening.startswith("tilt"):
            if opening != "tilt":                          # side-hung; a plain tilt (bottom-hung) has the triangle only
                hinge = x + w - inset if opening.endswith("left") else x + inset
                tip = x + inset if opening.endswith("left") else x + w - inset
                parts.append(f'<path d="M{hinge:.1f} {y + inset:.1f} L{tip:.1f} {cy:.1f} L{hinge:.1f} {y + h - inset:.1f}" '
                             f'stroke="#4338CA" stroke-width=".9" stroke-dasharray="3 2" fill="none"/>')
            if opening.startswith("tilt"):
                parts.append(f'<path d="M{x + inset:.1f} {y + h - inset:.1f} L{cx:.1f} {y + inset:.1f} '
                             f'L{x + w - inset:.1f} {y + h - inset:.1f}" stroke="#4338CA" stroke-width=".9" '
                             f'stroke-dasharray="3 2" fill="none"/>')
    if show:
        line = 'stroke="#0F172A" stroke-width=".7"'
        text = 'font-size="8.5" font-family="Cairo, Arial, sans-serif" fill="#0F172A" text-anchor="middle"'
        y = my - 5
        parts.append(f'<path d="M{mx} {y} H{mx + W:.1f} M{mx} {y - 3} v6 M{mx + W:.1f} {y - 3} v6" {line}/>')
        parts.append(f'<text x="{mx + W / 2:.1f}" y="{y - 2}" {text}>{cm(label_w or width_mm)} سم</text>')
        x = mx - 6
        parts.append(f'<path d="M{x} {my} V{my + H:.1f} M{x - 3} {my} h6 M{x - 3} {my + H:.1f} h6" {line}/>')
        parts.append(f'<text transform="translate({x - 3} {my + H / 2:.1f}) rotate(-90)" {text}>{cm(label_h or height_mm)} سم</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {mx + W + 4:.1f} {my + H + 4:.1f}" width="{mx + W + 4:.0f}" '
           f'height="{my + H + 4:.0f}" direction="ltr">{"".join(parts)}</svg>')
    return Markup(svg)


env.globals.update(drawing=drawing_svg)


def company_context(db, company_id) -> dict:
    from app.modules.org.models import Company
    from app.modules.org.settings import branding, get_company_settings

    company = db.get(Company, company_id)
    b = branding(db, company)
    b["logo"] = data_uri(db, b.get("logo_media_id"))
    b["currency"] = get_company_settings(db, company_id).currency
    return b


def render(template: str, **ctx) -> str:
    return env.get_template(template).render(**ctx)
