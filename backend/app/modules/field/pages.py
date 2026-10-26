"""The technicians' mobile app: one page served by the server itself at /tech (open it on the phone's browser,
then "Add to home screen"). It talks to the same API as the desktop program, so both always show the same jobs.
No offline storage: it works while the phone reaches the server."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

STATIC = Path(__file__).with_name("static")
router = APIRouter(include_in_schema=False)
_NO_CACHE = {"Cache-Control": "no-cache"}


@router.get("/tech")
def tech_page():
    return FileResponse(STATIC / "tech.html", media_type="text/html; charset=utf-8", headers=_NO_CACHE)


@router.get("/tech/icon.png")
def tech_icon():
    return FileResponse(STATIC / "icon.png", media_type="image/png")


@router.get("/tech/logo.png")
def tech_logo():
    return FileResponse(STATIC / "logo.png", media_type="image/png")


@router.get("/tech/manifest.webmanifest")
def tech_manifest():
    return JSONResponse({
        "name": "MYTech الفني", "short_name": "MYTech", "lang": "ar", "dir": "rtl", "start_url": "/tech",
        "scope": "/tech", "display": "standalone", "background_color": "#F3F5F9", "theme_color": "#5048E5",
        "icons": [{"src": "/tech/icon.png", "sizes": "256x256", "type": "image/png", "purpose": "any"}],
    }, media_type="application/manifest+json")


# installable as an app; it caches nothing (every request goes to the server)
_SW = "self.addEventListener('install', () => self.skipWaiting());\n" \
      "self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));\n" \
      "self.addEventListener('fetch', () => {});\n"


@router.get("/tech/sw.js")
def tech_sw():
    return Response(_SW, media_type="text/javascript", headers={**_NO_CACHE, "Service-Worker-Allowed": "/tech"})
