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

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.modules.library.models import MediaFile

TEMPLATES = Path(__file__).with_name("templates")
env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def cm(mm) -> str:
    if mm is None or mm == "":
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


env.filters.update(cm=cm, money=money)
env.globals.update(size=size)


def data_uri(db, media_id) -> str | None:
    from app.modules.library.router import media_path

    if not media_id:
        return None
    media = db.get(MediaFile, uuid.UUID(str(media_id)))
    if media is None or not media_path(media.sha256).exists():
        return None
    return f"data:{media.mime};base64," + base64.b64encode(media_path(media.sha256).read_bytes()).decode()


def drawing_svg(elements: list, width_mm=None, height_mm=None, max_w: int = 150, max_h: int = 120) -> Markup:
    """Generic drawing from the engine's drawing elements (frame / sash / glass / mullion)."""
    elements = elements or []
    if not elements and not (width_mm and height_mm):
        return Markup("")
    fw = Decimal(str(width_mm or max((Decimal(str(e.get("w_mm", 0))) for e in elements), default=1)))
    fh = Decimal(str(height_mm or max((Decimal(str(e.get("h_mm", 0))) for e in elements), default=1)))
    scale = min(Decimal(max_w - 8) / fw, Decimal(max_h - 8) / fh)
    W, H = float(fw * scale), float(fh * scale)
    parts = [f'<rect x="4" y="4" width="{W:.1f}" height="{H:.1f}" fill="#F8FAFC" stroke="#334155" stroke-width="1.4"/>']
    for e in elements:
        x = 4 + float(Decimal(str(e.get("x_mm", 0))) * scale)
        y = 4 + float(Decimal(str(e.get("y_mm", 0))) * scale)
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
            hinge = x + w - inset if opening.endswith("left") else x + inset
            tip = x + inset if opening.endswith("left") else x + w - inset
            parts.append(f'<path d="M{hinge:.1f} {y + inset:.1f} L{tip:.1f} {cy:.1f} L{hinge:.1f} {y + h - inset:.1f}" '
                         f'stroke="#4338CA" stroke-width=".9" stroke-dasharray="3 2" fill="none"/>')
            if opening.startswith("tilt"):
                parts.append(f'<path d="M{x + inset:.1f} {y + h - inset:.1f} L{cx:.1f} {y + inset:.1f} '
                             f'L{x + w - inset:.1f} {y + h - inset:.1f}" stroke="#4338CA" stroke-width=".9" '
                             f'stroke-dasharray="3 2" fill="none"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W + 8:.1f} {H + 8:.1f}" width="{W + 8:.0f}" '
           f'height="{H + 8:.0f}" direction="ltr">{"".join(parts)}</svg>')
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
