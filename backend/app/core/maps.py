"""Map links: the place of a survey / maintenance visit as a Google Maps link (what customers send on WhatsApp).

Coordinates are read from the link when it carries them. Short links (maps.app.goo.gl) carry none: the server
follows them once when it has internet; otherwise only the link is kept and still opens on the map.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit

log = logging.getLogger("mytech.maps")
_NUM = r"(-?\d{1,3}(?:\.\d+)?)"
_PATTERNS = [
    re.compile(rf"!3d{_NUM}!4d{_NUM}"),                       # place pin (most exact)
    re.compile(rf"[?&](?:q|query|ll|destination|daddr)={_NUM},\s*{_NUM}"),
    re.compile(rf"@{_NUM},{_NUM}"),                          # map centre
    re.compile(rf"^geo:{_NUM},{_NUM}"),
    re.compile(rf"^\s*{_NUM}\s*[,،]\s*{_NUM}\s*$"),           # "30.0444, 31.2357" typed by hand
]
_SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl"}
SIX = Decimal("0.000001")


def coordinates(text: str | None) -> tuple[Decimal, Decimal] | None:
    if not text:
        return None
    text = unquote(text.strip())
    for pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                lat, lng = Decimal(m.group(1)), Decimal(m.group(2))
            except InvalidOperation:
                continue
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat.quantize(SIX), lng.quantize(SIX)
    return None


def _expand(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in _SHORT_HOSTS:
        return None   # only Google's own short links are followed (nothing else is fetched)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=4) as r:
            return r.geturl()
    except Exception as exc:  # offline factory server: keep the link without coordinates
        log.info("map link not expanded: %s", type(exc).__name__)
        return None


def locate(url: str | None) -> tuple[Decimal, Decimal] | None:
    found = coordinates(url)
    if found is None and url:
        expanded = _expand(url.strip())
        found = coordinates(expanded) if expanded else None
    return found


def fill_location(data: dict) -> dict:
    """For create/update bodies: coordinates from the link unless typed explicitly."""
    if data.get("location_url") and data.get("latitude") is None and data.get("longitude") is None:
        found = locate(data["location_url"])
        if found:
            data["latitude"], data["longitude"] = found
    elif "location_url" in data and not data["location_url"]:   # link removed: the place goes with it
        data["location_url"] = data["latitude"] = data["longitude"] = None
    return data
