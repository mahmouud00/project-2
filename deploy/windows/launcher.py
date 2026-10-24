"""Started by the Windows service. Runs the version recorded in current.json,
so an update (or a rollback) only has to switch that file.

    <root>\python\python.exe <root>\service\launcher.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("MYTECH_ROOT", Path(__file__).resolve().parents[1]))
current = json.loads((ROOT / "current.json").read_text(encoding="utf-8"))
version_dir = ROOT / current["path"]
sys.path[:0] = [str(version_dir), str(version_dir / "site-packages")]
os.chdir(ROOT / "config")  # .env, license\, media\ ... are resolved from here

from app.server import serve  # noqa: E402

serve()
