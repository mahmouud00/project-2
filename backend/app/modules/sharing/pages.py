"""The page a customer opens from a shared link (no account): the quotation or invoice as printed, and for a sent
quotation two buttons: approve it, or ask for a change (with a note). Answering once is enough; the sales people are
notified. An expired or cancelled link says so. Link previews (WhatsApp, bots) are not counted as the customer."""
from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.core.audit import audit, snapshot
from app.db.base import utcnow
from app.db.session import system_session, tenant_session
from app.modules.sharing.models import DocumentShare
from app.modules.sharing.router import token_hash

router = APIRouter(include_in_schema=False)

BOTS = ("whatsapp", "facebookexternalhit", "bot", "crawler", "spider", "preview", "telegram", "slack", "discord")


def _message(title: str, text: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(title)}</title></head>
<body style="font-family:Tahoma,Arial,sans-serif;background:#F1F5F9;display:grid;place-items:center;min-height:90vh;margin:0">
<div style="background:#fff;border-radius:14px;padding:28px;max-width:420px;box-shadow:0 4px 20px rgba(0,0,0,.08);text-align:center">
<h2 style="margin:0 0 10px">{html.escape(title)}</h2><p style="color:#475569;margin:0">{html.escape(text)}</p></div></body></html>""",
                        status_code=status)


def _lookup(token: str) -> DocumentShare | None:
    with system_session() as sdb:              # the link names no company: find it by its token's hash
        share = sdb.scalar(select(DocumentShare).where(DocumentShare.token_hash == token_hash(token)))
        if share is not None:
            sdb.expunge(share)
        return share


def _open(token: str):
    """(share, tenant session, context) for a live link, or an HTMLResponse explaining why not."""
    from app.modules.deletions.router import full_context

    if len(token) > 100:
        return _message("اللينك ده مش صحيح", "اتأكد من اللينك أو اطلب لينك جديد من الشركة.", 404)
    found = _lookup(token)
    if found is None:
        return _message("اللينك ده مش صحيح", "اتأكد من اللينك أو اطلب لينك جديد من الشركة.", 404)
    if found.revoked_at is not None or found.expires_at <= datetime.now(timezone.utc):
        return _message("اللينك ده انتهى", "اطلب من الشركة تبعتلك لينك جديد.", 410)
    db = tenant_session(found.company_id, None)
    ctx = full_context(found.company_id, found.created_by or uuid.UUID(int=0))
    share = db.get(DocumentShare, found.id)
    return share, db, ctx


def _panel(share: DocumentShare, token: str, status: str) -> str:
    style = """<style>.share-panel{font-family:Tahoma,Arial,sans-serif;max-width:820px;margin:14px auto;background:#EEF2FF;
border:1px solid #C7D2FE;border-radius:12px;padding:14px 16px;direction:rtl}.share-panel b{font-size:15px}
.share-panel form{display:inline-block;margin:8px 0 0 8px}.share-panel button{font:inherit;border:0;border-radius:9px;padding:9px 16px;
cursor:pointer}.share-panel .ok{background:#16A34A;color:#fff}.share-panel .change{background:#fff;border:1px solid #CBD5E1}
.share-panel textarea{width:100%;box-sizing:border-box;margin-top:8px;border:1px solid #CBD5E1;border-radius:8px;padding:8px;font:inherit}
@media print{.share-panel{display:none}}</style>"""
    if share.response == "accepted":
        body = "<b>✓ شكرًا، اتسجلت موافقتك على العرض.</b> الشركة هتتواصل معاك."
    elif share.response == "change_requested":
        body = "<b>اتبعت طلب التعديل.</b> الشركة هتراجعه وتتواصل معاك."
    elif share.doc_type != "quotation":
        return ""
    elif status != "sent":
        body = "<b>العرض ده مش مستني رد دلوقتي.</b> لو عندك سؤال كلّم الشركة."
    else:
        t = html.escape(token)
        body = f"""<b>موافق على عرض السعر ده؟</b>
<form method="post" action="/s/{t}/accept"><button class="ok" type="submit">✓ موافق على العرض</button></form>
<form method="post" action="/s/{t}/change" style="display:block"><textarea name="note" rows="2" maxlength="1000"
placeholder="لو عايز تعديل، اكتبه هنا (المقاسات، العدد، اللون…)" required></textarea>
<button class="change" type="submit">ابعت طلب التعديل</button></form>"""
    return style + f'<div class="share-panel">{body}</div>'


def _render(share: DocumentShare, db, ctx) -> tuple[str, str]:
    from app.modules.documents.router import print_invoice, print_quotation
    from app.modules.invoicing.models import Invoice
    from app.modules.sales.models import Quotation

    if share.doc_type == "quotation":
        q = db.get(Quotation, share.doc_id)
        if q is None or q.deleted_at is not None:
            return "", ""
        return print_quotation(share.doc_id, dc=(db, ctx)).body.decode(), q.status
    inv = db.get(Invoice, share.doc_id)
    if inv is None or inv.deleted_at is not None:
        return "", ""
    return print_invoice(share.doc_id, dc=(db, ctx)).body.decode(), inv.status


@router.get("/s/{token}", response_class=HTMLResponse)
def view(token: str, request: Request):
    opened = _open(token)
    if isinstance(opened, HTMLResponse):
        return opened
    share, db, ctx = opened
    try:
        page, status = _render(share, db, ctx)
        if not page:
            return _message("المستند ده مش متاح", "كلّم الشركة.", 404)
        agent = (request.headers.get("user-agent") or "").lower()
        if not any(b in agent for b in BOTS):          # a link preview is not the customer opening it
            first = share.viewed_at is None
            share.views = (share.views or 0) + 1
            share.viewed_at = share.viewed_at or utcnow()
            if first and share.doc_type == "quotation":
                _notify(db, ctx, share, "فتح لينك عرض السعر")
        db.commit()
        panel = _panel(share, token, status)
        if "<body" in page:
            at = page.index(">", page.index("<body")) + 1
            page = page[:at] + panel + page[at:]
        # on a phone the A4 sheet is shown whole, zoomed to the screen's width
        head = '<head><meta name="robots" content="noindex"><meta name="viewport" content="width=860">'
        return HTMLResponse(page.replace("<head>", head, 1))
    finally:
        db.close()


def _notify(db, ctx, share: DocumentShare, what: str) -> None:
    from app.modules.notifications.router import alert, customer_name
    from app.modules.sales.models import Quotation

    q = db.get(Quotation, share.doc_id)
    users = {share.created_by} if share.created_by else None
    title = f"العميل {what} {q.number}"
    alert(db, ctx, "sales", q.branch_id, title, customer_name(db, q.customer_id), f"quotations/{q.id}")
    if users:                                   # and the one who sent the link, wherever they work
        alert(db, type("Nobody", (), {"user_id": None})(), "sales", q.branch_id, title,
              customer_name(db, q.customer_id), f"quotations/{q.id}", users=users)


def _answer(token: str, kind: str, note: str = ""):
    from app.licensing.service import entitlements
    from app.modules.sales.models import Quotation, QuotationLine
    from app.modules.sales.router import UNITS, _is_priced, _needs_price_approval

    opened = _open(token)
    if isinstance(opened, HTMLResponse):
        return opened
    share, db, ctx = opened
    try:
        if share.doc_type != "quotation" or share.response is not None:
            return RedirectResponse(f"/s/{token}", status_code=303)
        q = db.get(Quotation, share.doc_id)
        if q is None or q.deleted_at is not None or q.status != "sent":
            return RedirectResponse(f"/s/{token}", status_code=303)
        if not entitlements(db, share.company_id).can_write:
            return _message("مش متاح دلوقتي", "مش قادرين نسجل ردك دلوقتي. كلّم الشركة مباشرة.", 503)
        before_share = snapshot(share)
        if kind == "accept":
            blocked = any(not _is_priced(l) for l in db.scalars(select(QuotationLine).where(
                QuotationLine.quotation_id == q.id, UNITS))) or _needs_price_approval(q)
            if blocked:                       # the price changed since it was sent: the company must look again
                _notify(db, ctx, share, "حاول يوافق على عرض محتاج مراجعة")
                db.commit()
                return _message("العرض محتاج مراجعة", "العرض اتغيّر وبيتراجع من الشركة. هيتواصلوا معاك.")
            before = snapshot(q)
            q.status = "accepted"
            audit(db, q, "update", before, note="العميل وافق من اللينك")
            share.response = "accepted"
            _notify(db, ctx, share, "وافق على عرض السعر")
        else:
            share.response = "change_requested"
            share.response_note = note.strip()[:1000]
            _notify(db, ctx, share, "طلب تعديل على عرض السعر")
        share.responded_at = utcnow()
        audit(db, share, "update", before_share, note="رد العميل")
        db.commit()
        return RedirectResponse(f"/s/{token}", status_code=303)
    finally:
        db.close()


@router.post("/s/{token}/accept")
def accept(token: str):
    return _answer(token, "accept")


@router.post("/s/{token}/change")
def request_change(token: str, note: str = Form("", max_length=1000)):
    return _answer(token, "change", note)
