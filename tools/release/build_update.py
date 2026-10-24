"""Vendor: build a signed update file (*.mtu) for Windows servers.

    python tools/release/build_update.py --key ~/.mytech/vendor_private.pem --out dist/
        [--min-from 1.0.0] [--min-client 1.0.0] [--notes "..."] [--no-deps]

Reads the version from VERSION. Python dependencies are downloaded as Windows
wheels (cp312, win_amd64) into site-packages so the server needs no internet.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.licensing.signing import load_private_key  # noqa: E402
from app.ops.updater import build_package  # noqa: E402

DEPS = ["fastapi", "uvicorn", "sqlalchemy", "psycopg[binary]", "alembic", "pydantic", "pydantic-settings",
        "argon2-cffi", "pyjwt", "cryptography", "python-multipart", "openpyxl", "apscheduler<4", "zeroconf"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--key", default="~/.mytech/vendor_private.pem")
    p.add_argument("--out", default="dist")
    p.add_argument("--min-from", default="0.0.0")
    p.add_argument("--min-client", default="0.0.0")
    p.add_argument("--notes", default="")
    p.add_argument("--no-deps", action="store_true", help="code only (dependencies unchanged)")
    a = p.parse_args()
    version = (ROOT / "VERSION").read_text().strip()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / version
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".env")
        shutil.copytree(ROOT / "backend" / "app", src / "app", ignore=ignore)
        shutil.copytree(ROOT / "backend" / "migrations", src / "migrations", ignore=ignore)
        shutil.copy(ROOT / "backend" / "alembic.ini", src / "alembic.ini")
        shutil.copy(ROOT / "VERSION", src / "VERSION")
        if not a.no_deps:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--target", str(src / "site-packages"),
                                   "--platform", "win_amd64", "--python-version", "3.12", "--only-binary=:all:",
                                   "--implementation", "cp", *DEPS])
        key = load_private_key(Path(os.path.expanduser(a.key)).read_bytes(),
                               os.environ.get("MYTECH_KEY_PASSWORD", "").encode() or None)
        data = build_package(src, version, key, min_from_version=a.min_from, min_client_version=a.min_client,
                             notes=a.notes)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"mytech-{version}.mtu"
    target.write_bytes(data)
    print(f"{target} ({len(data) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
