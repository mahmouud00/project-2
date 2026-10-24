"""MYTech vendor tool — for the vendor only, never shipped to customers.

    python -m tools.vendor_admin keygen --out ~/.mytech/vendor_private.pem
    python -m tools.vendor_admin issue-license --key ~/.mytech/vendor_private.pem \
        --company-code ACME --company-name "ACME Windows" --fingerprint <from customer server> \
        --modules core,manufacturing,mfg.upvc,mfg.shutter --max-devices 10 --expires 2027-12-31 --out acme.lic.json
    python -m tools.vendor_admin show-license acme.lic.json
    python -m tools.vendor_admin create-company --code ACME --name "ACME" --admin admin      (online server)
    python -m tools.vendor_admin set-subscription --company ACME --modules core,manufacturing,mfg.upvc \
        --max-users 20 --max-branches 3 --max-devices 30 --expires 2027-12-31             (online server)
    python -m tools.vendor_admin list-subscriptions
    python -m tools.vendor_admin sign-package <library-package.zip> --key ...  (see library export)

Run from the repository root with PYTHONPATH=backend (the database tools use backend/.env).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.licensing.provider import MODULES  # noqa: E402
from app.licensing.signing import (generate_keypair, load_private_key, public_key_module,  # noqa: E402
                                   sign_document, verify_document, load_public_key)

from tools.vendor_admin.licenses import build_license  # noqa: E402

PUBLIC_KEY_MODULE = ROOT / "backend" / "app" / "licensing" / "vendor_key.py"


def _modules(value: str) -> list[str]:
    mods = [m.strip() for m in value.split(",") if m.strip()]
    unknown = [m for m in mods if m not in MODULES]
    if unknown:
        raise SystemExit(f"unknown modules: {unknown}; known: {sorted(MODULES)}")
    if any(m.startswith("mfg.") for m in mods) and "manufacturing" not in mods:
        mods.append("manufacturing")
    if "core" not in mods:
        mods.insert(0, "core")
    return mods


def _date(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).isoformat()


def _private_key(path: str):
    pem = Path(os.path.expanduser(path)).read_bytes()
    password = os.environ.get("MYTECH_KEY_PASSWORD")
    if password is None and b"ENCRYPTED" in pem:
        password = getpass.getpass("Private key passphrase: ")
    return load_private_key(pem, password.encode() if password else None)


def cmd_keygen(a) -> None:
    out = Path(os.path.expanduser(a.out))
    if out.exists() and not a.force:
        raise SystemExit(f"{out} exists (use --force to overwrite; old licences would stop verifying)")
    password = os.environ.get("MYTECH_KEY_PASSWORD") or getpass.getpass("New passphrase for the private key: ")
    priv, pub = generate_keypair(password.encode() if password else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(priv)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    target = Path(a.install_public) if a.install_public else PUBLIC_KEY_MODULE
    target.write_text(public_key_module(pub), encoding="utf-8")
    print(f"private key: {out}  (KEEP SECRET, BACK IT UP, NEVER COMMIT)")
    print(f"public key written to: {target}  (commit this one; it is compiled into the server)")


def cmd_issue(a) -> None:
    payload = build_license(company_code=a.company_code, company_name=a.company_name, fingerprint=a.fingerprint,
                            modules=_modules(a.modules), max_devices=a.max_devices, max_users=a.max_users,
                            max_branches=a.max_branches, expires=_date(a.expires), grace_days=a.grace_days,
                            notes=a.notes)
    doc = sign_document(_private_key(a.key), payload)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"licence {payload['license_id']} written to {a.out}")


def cmd_show(a) -> None:
    doc = json.loads(Path(a.file).read_text(encoding="utf-8"))
    ok = verify_document(doc, load_public_key())
    print(json.dumps(doc.get("payload"), ensure_ascii=False, indent=2))
    print("signature:", "VALID" if ok else "INVALID")


def _db():
    os.chdir(ROOT / "backend")
    from app.db import models  # noqa: F401
    from app.db.session import system_session
    return system_session()


def cmd_create_company(a) -> None:
    from app.modules.org.service import create_company

    password = a.password or getpass.getpass("Admin password: ")
    with _db() as db:
        company, _ = create_company(db, code=a.code, name=a.name, admin_username=a.admin, admin_password=password)
        db.commit()
        print(f"company {company.code} id={company.id}")


def cmd_set_subscription(a) -> None:
    from sqlalchemy import select, update

    from app.licensing.models import Subscription
    from app.modules.org.models import Company

    with _db() as db:
        company = db.scalar(select(Company).where(Company.code == a.company))
        if company is None:
            raise SystemExit("company not found")
        db.execute(update(Subscription).where(Subscription.company_id == company.id).values(is_active=False))
        db.add(Subscription(company_id=company.id, modules=_modules(a.modules), max_users=a.max_users,
                            max_branches=a.max_branches, max_devices=a.max_devices,
                            starts_at=datetime.now(timezone.utc),
                            expires_at=datetime.fromisoformat(_date(a.expires))))
        db.commit()
        print(f"subscription set for {company.code} until {a.expires}")


def cmd_list_subscriptions(a) -> None:
    from sqlalchemy import select

    from app.licensing.models import Subscription
    from app.modules.org.models import Company

    with _db() as db:
        rows = db.execute(select(Company.code, Subscription).join(Subscription, Subscription.company_id == Company.id)
                          .where(Subscription.is_active).order_by(Company.code)).all()
        for code, s in rows:
            print(f"{code:15} {','.join(s.modules):45} users={s.max_users} branches={s.max_branches} "
                  f"devices={s.max_devices} expires={s.expires_at.date()}")


def cmd_sign_package(a) -> None:
    from app.licensing.signing import verify_document
    from app.modules.library.packages import sign_package

    data = Path(a.package).read_bytes()
    signed = sign_package(data, _private_key(a.key))
    out = Path(a.out or a.package.replace(".unsigned", "").replace(".zip", ".signed.zip"))
    out.write_bytes(signed)
    import io, zipfile
    doc = json.loads(zipfile.ZipFile(io.BytesIO(signed)).read("package.json"))
    print(f"signed package {doc['payload']['package_id']} -> {out}")
    print("systems:", ", ".join(s["system"]["code"] for s in doc["payload"]["systems"]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vendor_admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", default="~/.mytech/vendor_private.pem")
    k.add_argument("--install-public")
    k.add_argument("--force", action="store_true")
    i = sub.add_parser("issue-license")
    i.add_argument("--key", default="~/.mytech/vendor_private.pem")
    i.add_argument("--company-code", required=True)
    i.add_argument("--company-name", required=True)
    i.add_argument("--fingerprint", required=True, help="shown on the customer server: GET /api/v1/system/license")
    i.add_argument("--modules", required=True)
    i.add_argument("--max-devices", type=int, required=True)
    i.add_argument("--max-users", type=int)
    i.add_argument("--max-branches", type=int)
    i.add_argument("--expires", help="YYYY-MM-DD; omit for perpetual")
    i.add_argument("--grace-days", type=int, default=14)
    i.add_argument("--notes", default="")
    i.add_argument("--out", required=True)
    s = sub.add_parser("show-license")
    s.add_argument("file")
    c = sub.add_parser("create-company")
    c.add_argument("--code", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--admin", default="admin")
    c.add_argument("--password")
    ss = sub.add_parser("set-subscription")
    ss.add_argument("--company", required=True)
    ss.add_argument("--modules", required=True)
    ss.add_argument("--max-users", type=int, required=True)
    ss.add_argument("--max-branches", type=int, required=True)
    ss.add_argument("--max-devices", type=int, required=True)
    ss.add_argument("--expires", required=True)
    sub.add_parser("list-subscriptions")
    sp = sub.add_parser("sign-package")
    sp.add_argument("package")
    sp.add_argument("--key", default="~/.mytech/vendor_private.pem")
    sp.add_argument("--out")
    a = p.parse_args(argv)
    {"keygen": cmd_keygen, "issue-license": cmd_issue, "show-license": cmd_show,
     "create-company": cmd_create_company, "set-subscription": cmd_set_subscription,
     "list-subscriptions": cmd_list_subscriptions, "sign-package": cmd_sign_package}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
