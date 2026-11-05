"""Share a quotation (to read and approve, or ask for a change) or an invoice (to read) with the customer by a link,
e.g. on WhatsApp. Each send makes a new link (an older message keeps working until its link expires); cancelling
cancels every link of the document.

A draft quotation is sent when shared, with the same checks as sending it (every line priced; a price under the
fair one approved). The customer's approval goes through the same checks again and notifies the sales people.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import audit, snapshot
from app.core.config import get_settings
from app.core.errors import Conflict
from app.db.base import utcnow
from app.modules.crm.router import get_or_404
from app.modules.sharing.models import DocumentShare
from app.tenancy.context import get_db_and_ctx

router = APIRouter(tags=["sharing"])


class ShareIn(BaseModel):
    days: int = Field(14, ge=1, le=60)


class ShareOut(BaseModel):
    id: uuid.UUID | None = None
    url: str | None = None                     # only when the link is made (the token is never stored)
    expires_at: datetime | None = None
    reachable_outside: bool = False            # False: the address only works inside the factory network
    active: bool = False
    viewed_at: datetime | None = None
    views: int = 0
    response: str | None = None
    response_note: str = ""
    responded_at: datetime | None = None
    customer_phone: str | None = None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _base_url(request: Request) -> tuple[str, bool]:
    s = get_settings()
    if s.public_url:
        return s.public_url.rstrip("/"), True
    return str(request.base_url).rstrip("/"), s.is_online


def _current(db, doc_type: str, doc_id) -> DocumentShare | None:
    return db.scalar(select(DocumentShare).where(DocumentShare.doc_type == doc_type, DocumentShare.doc_id == doc_id)
                     .order_by(DocumentShare.created_at.desc()).limit(1))


def _out(share: DocumentShare | None, phone: str | None, url: str | None = None, outside: bool = False) -> ShareOut:
    if share is None:
        return ShareOut(customer_phone=phone, reachable_outside=outside)
    active = share.revoked_at is None and share.expires_at > utcnow()
    return ShareOut(id=share.id, url=url, expires_at=share.expires_at, reachable_outside=outside, active=active,
                    viewed_at=share.viewed_at, views=share.views, response=share.response,
                    response_note=share.response_note, responded_at=share.responded_at, customer_phone=phone)


def _make(db, ctx, request: Request, doc_type: str, doc_id, days: int) -> tuple[DocumentShare, str, bool]:
    now = utcnow()
    token = secrets.token_urlsafe(32)
    share = DocumentShare(doc_type=doc_type, doc_id=doc_id, token_hash=token_hash(token), expires_at=now + timedelta(days=days),
                          views=0, response_note="")
    db.add(share)
    db.flush()
    audit(db, share, "create", note=f"link for {doc_type}")
    base, outside = _base_url(request)
    return share, f"{base}/s/{token}", outside


def _phone(db, customer_id) -> str | None:
    from app.modules.crm.models import Customer
    c = db.get(Customer, customer_id)
    return c.phone if c else None


# ---------------------------------------------------------------- quotations
@router.post("/quotations/{quote_id}/share", response_model=ShareOut)
def share_quotation(quote_id: uuid.UUID, body: ShareIn, request: Request, dc=Depends(get_db_and_ctx)):
    from app.modules.notifications.router import alert, customer_name
    from app.modules.sales.router import UNITS, _is_priced, _needs_price_approval
    from app.modules.sales.models import Quotation, QuotationLine

    db, ctx = dc
    q = get_or_404(db, Quotation, quote_id)
    ctx.require("quotes.write", q.branch_id)
    if q.status not in ("draft", "sent"):
        raise Conflict("Only a draft or sent quotation can be shared", code="QUOTE_NOT_SHAREABLE", details={"status": q.status})
    if q.status == "draft":                     # sharing is sending: the same checks
        if any(not _is_priced(l) for l in db.scalars(select(QuotationLine).where(QuotationLine.quotation_id == q.id, UNITS))):
            raise Conflict("Some lines have no price yet", code="QUOTE_UNPRICED")
        if _needs_price_approval(q):
            raise Conflict("The price is under the fair price: the sales manager must approve it", code="PRICE_APPROVAL_REQUIRED")
        before = snapshot(q)
        q.status = "sent"
        audit(db, q, "update", before, note="اتبعت للعميل بلينك")
        alert(db, ctx, "sales", q.branch_id, f"عرض السعر {q.number} اتبعت للعميل", customer_name(db, q.customer_id), f"quotations/{q.id}")
    share, url, outside = _make(db, ctx, request, "quotation", q.id, body.days)
    db.commit()
    return _out(share, _phone(db, q.customer_id), url, outside)


@router.get("/quotations/{quote_id}/share", response_model=ShareOut)
def quotation_share(quote_id: uuid.UUID, request: Request, dc=Depends(get_db_and_ctx)):
    from app.modules.sales.models import Quotation

    db, ctx = dc
    q = get_or_404(db, Quotation, quote_id)
    ctx.require("quotes.read", q.branch_id)
    return _out(_current(db, "quotation", q.id), _phone(db, q.customer_id), outside=_base_url(request)[1])


# ---------------------------------------------------------------- invoices
@router.post("/invoices/{inv_id}/share", response_model=ShareOut)
def share_invoice(inv_id: uuid.UUID, body: ShareIn, request: Request, dc=Depends(get_db_and_ctx)):
    from app.modules.invoicing.models import Invoice

    db, ctx = dc
    inv = get_or_404(db, Invoice, inv_id)
    ctx.require("treasury.write", inv.branch_id)
    if inv.status != "issued":
        raise Conflict("Only an issued invoice can be shared", code="INVOICE_NOT_ISSUED")
    share, url, outside = _make(db, ctx, request, "invoice", inv.id, body.days)
    db.commit()
    return _out(share, _phone(db, inv.customer_id), url, outside)


@router.get("/invoices/{inv_id}/share", response_model=ShareOut)
def invoice_share(inv_id: uuid.UUID, request: Request, dc=Depends(get_db_and_ctx)):
    from app.modules.invoicing.models import Invoice

    db, ctx = dc
    inv = get_or_404(db, Invoice, inv_id)
    ctx.require("treasury.read", inv.branch_id)
    return _out(_current(db, "invoice", inv.id), _phone(db, inv.customer_id), outside=_base_url(request)[1])


@router.post("/shares/{share_id}/revoke", response_model=ShareOut)  # cancels all the document's links
def revoke_share(share_id: uuid.UUID, dc=Depends(get_db_and_ctx)):
    db, ctx = dc
    share = db.get(DocumentShare, share_id)
    if share is None:
        from app.core.errors import NotFound
        raise NotFound("Link not found")
    ctx.require("quotes.write" if share.doc_type == "quotation" else "treasury.write")
    for live in db.scalars(select(DocumentShare).where(DocumentShare.doc_type == share.doc_type,
                                                       DocumentShare.doc_id == share.doc_id, DocumentShare.revoked_at.is_(None))):
        before = snapshot(live)                 # every link of the document stops working
        live.revoked_at = utcnow()
        audit(db, live, "update", before, note="link cancelled")
    db.commit()
    return _out(share, None)
