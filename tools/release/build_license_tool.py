"""Compile the MYTech Licence Tool (tkinter GUI) to a single native Windows executable with Nuitka.

    python tools/release/build_license_tool.py --out build/MYTech-License-Tool.exe --icon desktop/src-tauri/icons/icon.ico

The tool is for MYTech only (never shipped to customers). It contains the PUBLIC key only; the private key
is a separate encrypted file loaded at run time.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(ROOT / "build" / "MYTech-License-Tool.exe"))
    p.add_argument("--icon", default=None)
    a = p.parse_args()
    out = Path(a.out).resolve()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    work = out.parent / "license-tool-build"
    args = [
        sys.executable, "-m", "nuitka", "--onefile", "--assume-yes-for-downloads", "--enable-plugin=tk-inter",
        f"--output-dir={work}", f"--output-filename={out.name}",
        "--include-package=tools.vendor_admin", "--include-module=app.licensing.vendor_key",
        "--nofollow-import-to=pytest,_pytest,tests,uvicorn,apscheduler,zeroconf,openpyxl",
        "--python-flag=no_docstrings",
        "--product-name=MYTech Licence Tool", "--company-name=MYTech Solutions", f"--file-version={version}",
        f"--product-version={version}", "--file-description=MYTech Licence Tool", "--copyright=MYTech Solutions",
        "--windows-console-mode=disable", "--mingw64",
    ]
    if a.icon:
        args.append(f"--windows-icon-from-ico={Path(a.icon).resolve()}")
    args.append(str(ROOT / "tools" / "vendor_admin" / "gui.py"))
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / "backend")]))
    subprocess.run(args, check=True, cwd=str(ROOT), env=env)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(work / out.name), str(out))
    shutil.rmtree(work, ignore_errors=True)
    print(f"licence tool built: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
