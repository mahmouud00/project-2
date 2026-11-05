"""Updates from inside the program (IDEAS 7).

Client programs: every server build carries the desktop installer and the Android app next to the server program
(<install>\\app\\<version>\\clients\\). The programs ask GET /system/clients when they start and, when the server
holds a newer one, offer it: «فيه نسخة جديدة». So updating the server updates every PC and phone in the factory,
with no internet and no link to send around.

Server: an admin uploads the signed update file (*.mtu) from the program. The server checks the MYTech signature
and that it is newer, then hands it to a Windows scheduled task that runs scripts\\update.ps1 (the same safe update:
backup first, migrate with the new version, health check, automatic rollback). The task runs outside the service,
because the update has to stop the service.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, ValidationFailed
from app.core.versioning import parse
from app.tenancy.context import get_db_and_ctx

router = APIRouter(prefix="/system", tags=["system"])

KINDS = {"desktop": re.compile(r"^MYTech-Desktop-Setup-(\d+\.\d+\.\d+)\.exe$"),
         "android": re.compile(r"^MYTech-Mobile-(\d+\.\d+\.\d+)\.apk$")}
TASK = "MYTech Update"


def version_dir() -> Path:
    """The folder of the running server (app/<version>/ when installed; the repository's backend/ in development)."""
    return Path(__file__).resolve().parents[3]


def clients_dir() -> Path:
    s = get_settings()
    return Path(s.clients_dir) if s.clients_dir else version_dir() / "clients"


def _newest(kind: str) -> tuple[str, Path] | None:
    folder = clients_dir()
    if not folder.is_dir():
        return None
    found = [(m.group(1), f) for f in folder.iterdir() if (m := KINDS[kind].match(f.name)) and f.is_file()]
    return max(found, key=lambda x: parse(x[0])) if found else None


@router.get("/clients")
def clients():
    """(Public) the newest desktop / phone program this server holds, to offer it to older ones."""
    out = {}
    for kind in KINDS:
        n = _newest(kind)
        out[kind] = {"version": n[0], "size": n[1].stat().st_size, "file": n[1].name,
                     "url": f"/api/v1/system/clients/{kind}"} if n else None
    return out


@router.get("/clients/{kind}")
def client_download(kind: str):
    if kind not in KINDS or (n := _newest(kind)) is None:
        raise NotFound("No program of that kind on this server")
    media = "application/vnd.android.package-archive" if kind == "android" else "application/octet-stream"
    return FileResponse(n[1], media_type=media, filename=n[1].name)


# ---------------------------------------------------------------- server update
def on_windows() -> bool:
    return os.name == "nt"


def install_root() -> Path | None:
    """<install> when this is an installed Windows server (it has current.json), else None."""
    if os.environ.get("MYTECH_ROOT"):
        root = Path(os.environ["MYTECH_ROOT"])
    else:
        root = version_dir().parents[1]
    return root if (root / "current.json").exists() else None


def _require_admin(ctx) -> None:
    ctx.require("system.manage")
    if get_settings().is_online and not ctx.is_platform:
        from app.core.errors import Forbidden
        raise Forbidden("The online server is updated by MYTech", code="PLATFORM_ONLY")


def _log_tail(root: Path | None, lines: int = 12) -> list[str]:
    if root is None:
        return []
    try:
        return (root / "logs" / "updates.log").read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []


@router.get("/update")
def update_status(dc=Depends(get_db_and_ctx)):
    _require_admin(dc[1])
    root = install_root()
    return {"version": get_settings().version, "can_update": root is not None and on_windows(),
            "log": _log_tail(root)}


def schedule(root: Path, package: Path) -> None:
    """Run scripts\\update.ps1 for the package as a one-off Windows task (outside this service)."""
    script = root / "updates" / "run-update.cmd"
    script.write_text(
        "@echo off\r\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{root / "scripts" / "update.ps1"}" '
        f'-Package "{package}" -Root "{root}" -HttpPort {get_settings().http_port} >> "{root / "logs" / "updates.log"}" 2>&1\r\n'
        f'schtasks /Delete /TN "{TASK}" /F >nul 2>&1\r\n', encoding="utf-8")
    run = f'"{script}"' if " " in str(script) else str(script)
    for cmd in (["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "ONCE", "/ST", "00:00", "/RU", "SYSTEM",
                 "/RL", "HIGHEST", "/TR", run],
                ["schtasks", "/Run", "/TN", TASK]):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise AppError(f"Could not start the update ({(p.stderr or p.stdout).strip()[:200]})",
                           code="UPDATE_NOT_STARTED", status_code=500)


@router.post("/update", status_code=202)
async def upload_update(file: UploadFile, dc=Depends(get_db_and_ctx)):
    from app.ops.updater import UpdateError, read_package

    _require_admin(dc[1])
    data = await file.read()
    try:
        manifest, _ = read_package(data)
    except UpdateError as e:
        raise ValidationFailed(str(e), code="UPDATE_INVALID")
    current = get_settings().version
    if parse(manifest["version"]) <= parse(current):
        raise Conflict(f"Version {manifest['version']} is not newer than {current}", code="UPDATE_NOT_NEWER",
                       details={"version": manifest["version"], "current": current})
    root = install_root()
    if root is None or not on_windows():
        raise Conflict("This server is not an installed Windows server: update it with its own tools",
                       code="UPDATE_UNAVAILABLE")
    folder = root / "updates"
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.mtu"):
        old.unlink(missing_ok=True)
    package = folder / f"mytech-{manifest['version']}.mtu"
    package.write_bytes(data)
    schedule(root, package)
    return {"version": manifest["version"], "from": current, "notes": manifest.get("notes", "")}
