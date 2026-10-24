"""Compile the server to a native executable with Nuitka (Python -> C -> machine code; no .py/.pyc
of the application ships). Used by the Windows release workflow and for local checks on Linux.

    python tools/release/build_server.py --out build/server

Output folder (becomes <root>\\app\\<version>\\ on the server PC):
    mytech-server(.exe)  + its libraries
    migrations\\ alembic.ini VERSION      (Alembic reads migration scripts from disk)
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def nuitka_args(out: Path, version: str, icon: Path | None, jobs: int | None) -> list[str]:
    win = platform.system() == "Windows"
    args = [
        sys.executable, "-m", "nuitka", "--standalone", "--assume-yes-for-downloads",
        f"--output-dir={out.parent}", "--output-filename=mytech-server" + (".exe" if win else ""),
        "--include-package=app", "--include-package-data=app",
        "--include-package=alembic", "--include-package-data=alembic",
        "--include-package=uvicorn", "--include-package=h11",
        "--include-package=psycopg", "--include-package=psycopg_binary",
        "--include-package=sqlalchemy.dialects.postgresql",
        "--include-package=apscheduler", "--include-distribution-metadata=apscheduler",
        "--include-package=zeroconf", "--include-package=multipart", "--include-package=python_multipart",
        "--nofollow-import-to=pytest,_pytest,tests,openpyxl.tests",
        "--python-flag=no_docstrings", "--python-flag=no_asserts",
        "--product-name=MYTech Solutions Server", "--company-name=MYTech Solutions",
        f"--file-version={version}", f"--product-version={version}", "--file-description=MYTech Solutions Server",
        "--copyright=MYTech Solutions",
    ]
    if win:
        args += ["--mingw64", "--windows-console-mode=attach"]
        if icon:
            args.append(f"--windows-icon-from-ico={icon}")
    if jobs:
        args.append(f"--jobs={jobs}")
    args.append(str(BACKEND / "mytech_server.py"))
    return args


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "build" / "server"))
    p.add_argument("--icon", default=None)
    p.add_argument("--jobs", type=int, default=None)
    a = p.parse_args()
    out = Path(a.out).resolve()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if out.exists():
        shutil.rmtree(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(BACKEND))
    subprocess.run(nuitka_args(out, version, Path(a.icon) if a.icon else None, a.jobs), check=True, cwd=str(BACKEND), env=env)
    dist = out.parent / "mytech_server.dist"
    if out.exists():
        shutil.rmtree(out)
    dist.rename(out)
    # Alembic loads env.py and the migration scripts from disk at run time
    shutil.copytree(BACKEND / "migrations", out / "migrations", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(BACKEND / "alembic.ini", out / "alembic.ini")
    shutil.copy2(ROOT / "VERSION", out / "VERSION")
    print(f"server built: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
