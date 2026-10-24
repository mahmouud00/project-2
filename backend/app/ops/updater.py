"""Safe updates of an installed server (offline customers; also used on the online server).

Install layout (root, e.g. C:\\MYTech):
    current.json            {"version": "1.2.0", "path": "app/1.2.0", "previous": {...}}
    app/<version>/          code (app/, migrations/, alembic.ini, VERSION) + site-packages/
    config/.env             settings (never touched by updates)
    backups/ media/ license/ logs/

Update file (*.mtu, zip):
    manifest.json           signed {"payload": {"version", "min_from_version", "min_client_version", "notes",
                                    "created_at", "files": {relative_path: sha256}}, "signature"}
    payload/...             files of the new version (relative to app/<version>/)

apply_update():
    verify signature + hashes + version rules
    -> backup (mandatory) -> stop service -> unpack to app/<new> -> run migrations with the NEW code
    -> switch current.json -> start service -> health check (must report the new version)
    any failure after the backup: stop -> restore backup -> switch back -> start -> report
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.core.versioning import parse
from app.licensing.signing import verify_document

log = logging.getLogger("mytech.updater")


class UpdateError(Exception):
    pass


@dataclass
class ServiceController:
    """How to stop/start the API and check it is healthy. Windows uses the
    WinSW service; tests inject callables."""
    stop: Callable[[], None]
    start: Callable[[], None]
    healthy: Callable[[str], bool]  # expected version -> ok


def windows_service(name: str = "MYTechServer", port: int = 8000, timeout: int = 60) -> ServiceController:
    def run(*args):
        subprocess.run(["sc", *args, name], capture_output=True, text=True)

    def wait_stopped():
        run("stop")
        for _ in range(timeout):
            out = subprocess.run(["sc", "query", name], capture_output=True, text=True).stdout
            if "STOPPED" in out:
                return
            time.sleep(1)
        raise UpdateError("service did not stop")

    return ServiceController(stop=wait_stopped, start=lambda: run("start"),
                             healthy=lambda v: http_health(f"http://127.0.0.1:{port}", v, timeout))


def http_health(base: str, expected_version: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/v1/system/info", timeout=3) as r:
                if json.loads(r.read()).get("version") == expected_version:
                    with urllib.request.urlopen(f"{base}/api/v1/system/health", timeout=3) as h:
                        return h.status == 200
        except Exception:
            pass
        time.sleep(1)
    return False


# ---------------------------------------------------------------- package
def read_package(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise UpdateError("Not an update file")
    if not verify_document(doc):
        raise UpdateError("Update signature is not valid")
    manifest = doc["payload"]
    names = set(z.namelist())
    for rel, digest in manifest["files"].items():
        name = f"payload/{rel}"
        if name not in names or hashlib.sha256(z.read(name)).hexdigest() != digest:
            raise UpdateError(f"Update file corrupted: {rel}")
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise UpdateError("Invalid path in update")
    return manifest, z


def build_package(source_dir: Path, version: str, private_key, *, min_from_version: str = "0.0.0",
                  min_client_version: str = "0.0.0", notes: str = "") -> bytes:
    """Vendor side: zip a prepared version directory and sign its manifest."""
    from app.licensing.signing import sign_document

    files = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                rel = path.relative_to(source_dir).as_posix()
                data = path.read_bytes()
                files[rel] = hashlib.sha256(data).hexdigest()
                z.writestr(f"payload/{rel}", data)
        manifest = {"format": 1, "version": version, "min_from_version": min_from_version,
                    "min_client_version": min_client_version, "notes": notes,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": files}
        z.writestr("manifest.json", json.dumps(sign_document(private_key, manifest), ensure_ascii=False))
    return buf.getvalue()


# ---------------------------------------------------------------- install state
def read_current(root: Path) -> dict:
    try:
        return json.loads((root / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UpdateError("Installation not found (current.json missing)")


def write_current(root: Path, state: dict) -> None:
    tmp = root / "current.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(root / "current.json")


def run_migrations(version_dir: Path, config_dir: Path, python: str = sys.executable) -> None:
    env = dict(os.environ)
    paths = [str(version_dir), str(version_dir / "site-packages")]
    env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.run([python, "-m", "app.cli", "migrate"], cwd=str(config_dir), env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise UpdateError(f"migration failed: {proc.stderr.strip()[-1500:]}")


def _log(root: Path, message: str) -> None:
    (root / "logs").mkdir(exist_ok=True)
    with (root / "logs" / "updates.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    log.info(message)


def apply_update(root: Path, package: bytes, service: ServiceController, *, python: str = sys.executable,
                 db_url: str | None = None) -> dict:
    from app.ops.backup import restore, run_backup

    root = Path(root)
    manifest, z = read_package(package)
    current = read_current(root)
    new_v, cur_v = manifest["version"], current["version"]
    if parse(new_v) <= parse(cur_v):
        raise UpdateError(f"Version {new_v} is not newer than installed {cur_v}")
    if parse(cur_v) < parse(manifest.get("min_from_version", "0.0.0")):
        raise UpdateError(f"Install {manifest['min_from_version']} or later first")
    _log(root, f"update {cur_v} -> {new_v} started")

    backup = run_backup(label=f"pre-update-{new_v}", dest=root / "backups", url=db_url)
    _log(root, f"backup {backup.name}")
    target = root / "app" / new_v
    config_dir = root / "config"
    service.stop()
    try:
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for rel in manifest["files"]:
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(f"payload/{rel}"))
        run_migrations(target, config_dir, python)
        write_current(root, {"version": new_v, "path": f"app/{new_v}", "previous": current,
                             "updated_at": datetime.now(timezone.utc).isoformat()})
        service.start()
        if not service.healthy(new_v):
            raise UpdateError("new version did not start correctly")
    except Exception as exc:
        _log(root, f"update failed: {exc}; rolling back")
        try:
            service.stop()
        except Exception:
            pass
        restore(backup, safety_backup=False, url=db_url)
        write_current(root, current)
        service.start()
        _log(root, f"rolled back to {cur_v}")
        raise UpdateError(f"Update to {new_v} failed and was rolled back: {exc}") from exc
    _log(root, f"update to {new_v} done")
    return {"from": cur_v, "to": new_v, "backup": backup.name}


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="mytech-update")
    p.add_argument("package")
    p.add_argument("--root", default=os.environ.get("MYTECH_ROOT", "C:\\MYTech"))
    p.add_argument("--service", default="MYTechServer")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)
    result = apply_update(Path(a.root), Path(a.package).read_bytes(), windows_service(a.service, a.port))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
