"""Started by the Windows service (compiled to service\\mytech-service.exe). Runs the version recorded
in current.json, so an update (or a rollback) only has to switch that file.

    <root>\\service\\mytech-service.exe          -> <root>\\app\\<version>\\mytech-server.exe serve
    (older installs) <root>\\python\\python.exe <root>\\service\\launcher.py  -> app.server.serve()
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def root_dir() -> Path:
    if os.environ.get("MYTECH_ROOT"):
        return Path(os.environ["MYTECH_ROOT"])
    here = Path(sys.executable if getattr(sys, "frozen", False) or "__compiled__" in globals() else __file__).resolve()
    return here.parents[1]


def main() -> int:
    root = root_dir()
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    version_dir = root / current["path"]
    config_dir = root / "config"
    exe = version_dir / "mytech-server.exe"
    if exe.exists():
        env = dict(os.environ, MYTECH_ROOT=str(root))
        proc = subprocess.Popen([str(exe), "serve"], cwd=str(config_dir), env=env)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            return proc.wait()
    # source layout (embeddable Python)
    sys.path[:0] = [str(version_dir), str(version_dir / "site-packages")]
    os.chdir(config_dir)
    from app.server import serve
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
