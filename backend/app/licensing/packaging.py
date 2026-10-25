"""Signing of library update packages (no database or web dependencies: also used by the licence tool)."""
from __future__ import annotations

import io
import json
import zipfile


def sign_package(data: bytes, private_key) -> bytes:
    from app.licensing.signing import sign_document

    src = zipfile.ZipFile(io.BytesIO(data))
    doc = json.loads(src.read("package.json"))
    signed = sign_document(private_key, doc["payload"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.json", json.dumps(signed, ensure_ascii=False))
        for name in src.namelist():
            if name != "package.json":
                z.writestr(name, src.read(name))
    return out.getvalue()
