"""Find MYTech servers on the local network (UDP broadcast).

    python tools/find_server.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ops.discovery import discover  # noqa: E402

for server in discover(timeout=2.0):
    print(json.dumps(server, ensure_ascii=False))
