"""Licence document contents (signed by the licence tool / vendor CLI)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def build_license(*, company_code, company_name, fingerprint, modules, max_devices, max_users=None,
                  max_branches=None, expires=None, grace_days=14, notes="") -> dict:
    return {
        "format": 1,
        "license_id": str(uuid.uuid4()),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "company_code": company_code,
        "company_name": company_name,
        "machine_fingerprint": fingerprint,
        "modules": modules,
        "max_devices": max_devices,
        "max_users": max_users,
        "max_branches": max_branches,
        "expires_at": expires,
        "grace_days": grace_days,
        "notes": notes,
    }
