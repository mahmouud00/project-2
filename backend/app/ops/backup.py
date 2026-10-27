"""Database backups (pg_dump custom format) with checksum, retention and restore.

Pictures (model images, logos) are files in MEDIA_DIR, named by their content hash: every backup also copies
the new ones to <backup dir>/media. `export_bundle` / `import_bundle` put the database and the pictures in one
file to move an installation to another server (factory PC -> cloud VPS).

Backups run as the owner role (BYPASSRLS) so they contain every company.
Restore replaces the whole schema, then re-grants the runtime roles.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings

log = logging.getLogger("mytech.backup")


class BackupError(Exception):
    pass


def _tool(name: str) -> str:
    s = get_settings()
    if s.pg_bin_dir:
        candidate = Path(s.pg_bin_dir) / (name + (".exe" if os.name == "nt" else ""))
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise BackupError(f"{name} not found; set PG_BIN_DIR")
    return found


def _conn_args(url_str: str) -> tuple[list[str], dict]:
    url = make_url(url_str)
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username]
    return args, env


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def current_revision(url: str | None = None) -> str | None:
    engine = create_engine(url or get_settings().database_owner_url)
    try:
        with engine.connect() as c:
            return c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None
    finally:
        engine.dispose()


def run_backup(label: str = "daily", dest: Path | None = None, url: str | None = None) -> Path:
    s = get_settings()
    url = url or s.database_owner_url
    dest = Path(dest or s.backup_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = dest / f"mytech_{stamp}_v{s.version}_{label}.dump"
    args, env = _conn_args(url)
    db = make_url(url).database
    tmp = path.with_suffix(".partial")
    proc = subprocess.run([_tool("pg_dump"), *args, "-Fc", "--no-owner", "--no-privileges", "-f", str(tmp), db],
                          env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        _write_status(dest, ok=False, label=label, error=proc.stderr.strip()[-500:])
        raise BackupError(f"pg_dump failed: {proc.stderr.strip()[-500:]}")
    tmp.replace(path)
    try:
        sync_media(dest / "media")
    except OSError as e:   # the database backup is still good; say the pictures were not copied
        log.error("media not copied to the backup folder: %s", e)
    meta = {"file": path.name, "sha256": _sha256(path), "size": path.stat().st_size, "label": label,
            "app_version": s.version, "revision": current_revision(url),
            "created_at": datetime.now(timezone.utc).isoformat()}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    prune(dest, label)
    _write_status(dest, ok=True, label=label, file=path.name)
    log.info("backup written %s", path.name)
    return path


def sync_media(target: Path, source: Path | None = None) -> int:
    """Copy pictures that are not there yet (names are content hashes, files never change)."""
    source = Path(source or get_settings().media_dir)
    if not source.exists():
        return 0
    copied = 0
    for f in source.rglob("*"):
        if f.is_file() and not f.name.startswith("."):
            to = target / f.relative_to(source)
            if not to.exists():
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, to)
                copied += 1
    return copied


def export_bundle(out: Path, url: str | None = None) -> Path:
    """One .zip with the whole installation's data: database + pictures (to move to another server)."""
    import tempfile
    import zipfile

    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        dump = run_backup(label="export", dest=Path(tmp), url=url)
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(dump, "database.dump")
            z.write(dump.with_suffix(".json"), "database.json")
            media = Path(get_settings().media_dir)
            if media.exists():
                for f in media.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        z.write(f, "media/" + f.relative_to(media).as_posix())
    log.info("export written %s", out.name)
    return out


def import_bundle(path: Path, url: str | None = None) -> dict:
    """Restore an export on this server (the service must be stopped): database, then pictures."""
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path) as z:
        root = Path(tmp).resolve()
        for name in z.namelist():   # never write outside the temporary folder
            if not (root / name).resolve().is_relative_to(root):
                raise BackupError(f"unsafe path in bundle: {name}")
        z.extractall(root)
        dump = root / "mytech_import.dump"
        (root / "database.dump").replace(dump)
        (root / "database.json").replace(dump.with_suffix(".json"))
        meta = json.loads(dump.with_suffix(".json").read_text(encoding="utf-8"))
        meta["file"] = dump.name
        dump.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        meta = restore(dump, url=url)
        meta["pictures"] = sync_media(Path(get_settings().media_dir), root / "media")
    return meta


def _write_status(dest: Path, **info) -> None:
    info["at"] = datetime.now(timezone.utc).isoformat()
    try:
        (dest / "last_status.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    except OSError:
        pass


def list_backups(dest: Path | None = None) -> list[dict]:
    dest = Path(dest or get_settings().backup_dir)
    out = []
    for meta in sorted(dest.glob("mytech_*.json"), reverse=True):
        try:
            out.append(json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def last_status(dest: Path | None = None) -> dict | None:
    p = Path(dest or get_settings().backup_dir) / "last_status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def prune(dest: Path, label: str) -> None:
    keep = max(get_settings().backup_keep, 1)
    files = sorted(dest.glob(f"mytech_*_{label}.dump"), reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def verify(path: Path) -> dict:
    meta_path = path.with_suffix(".json")
    if not meta_path.exists():
        raise BackupError("Backup metadata missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if _sha256(path) != meta["sha256"]:
        raise BackupError("Backup file is corrupted (checksum mismatch)")
    return meta


def grant_runtime_roles(conn) -> None:
    """Re-grant the API and system roles after the schema is recreated (run as owner)."""
    s = get_settings()
    owner = make_url(s.database_owner_url).username
    for role in {make_url(s.database_url).username, make_url(s.database_system_url).username}:
        r = '"' + role.replace('"', '""') + '"'
        o = '"' + owner.replace('"', '""') + '"'
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {r}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {r}"))
        conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {r}"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public "
                          f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {r}"))


def restore(path: Path, *, safety_backup: bool = True, url: str | None = None) -> dict:
    """Replace the database content with a backup. The service must be stopped."""
    path = Path(path)
    meta = verify(path)
    url = url or get_settings().database_owner_url
    if safety_backup:
        run_backup(label="pre-restore", url=url)
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    db = make_url(url).database
    with engine.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(a.pid) FROM pg_stat_activity a "
                       "JOIN pg_roles r ON r.rolname = a.usename "
                       "WHERE a.datname = :d AND a.pid <> pg_backend_pid() AND NOT r.rolsuper"), {"d": db})
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    args, env = _conn_args(url)
    proc = subprocess.run([_tool("pg_restore"), *args, "--no-owner", "--no-privileges", "--exit-on-error",
                           "-d", db, str(path)], env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackupError(f"pg_restore failed: {proc.stderr.strip()[-500:]}")
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        grant_runtime_roles(c)
    engine.dispose()
    log.info("restored %s", path.name)
    return meta
