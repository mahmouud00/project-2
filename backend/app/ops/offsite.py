"""A second, encrypted copy of every backup outside the factory (IDEAS 8).

The copy goes to a folder the admin chooses: a Google Drive / OneDrive folder on the server PC (their own program
uploads it whenever there is internet), a network drive or a USB disk. The server itself never needs the internet.

Each database backup is written there encrypted with the admin's password (AES-256-GCM, key from scrypt), so whoever
gets the file (Google, someone with the drive) cannot read it. Pictures are copied encrypted the same way. Without the
password the copy cannot be opened, by anyone, MYTech included:
    mytech-server decrypt-backup <file.mtb> <out.dump> --password-file <file>

Settings (folder + password) are kept in <backup_dir>/offsite.json; the password is itself encrypted with a key from
JWT_SECRET, so the file alone does not give it away.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import struct
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings

log = logging.getLogger("mytech.offsite")

MAGIC = b"MYTB1"
CHUNK = 1 << 20
EXT = ".mtb"


class OffsiteError(Exception):
    pass


# ---------------------------------------------------------------- encryption
def _key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def encrypt_file(src: Path, dst: Path, password: str) -> None:
    """MAGIC | salt(16) | nonce prefix(8) | chunks: len(4) + AES-GCM(chunk, aad = index + last flag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, prefix = os.urandom(16), os.urandom(8)
    aes = AESGCM(_key(password, salt))
    tmp = dst.with_name(dst.name + ".partial")
    size = src.stat().st_size
    with src.open("rb") as fin, tmp.open("wb") as out:
        out.write(MAGIC + salt + prefix)
        i, done = 0, 0
        while True:
            block = fin.read(CHUNK)
            done += len(block)
            last = done >= size
            aad = struct.pack(">I?", i, last)
            sealed = aes.encrypt(prefix + struct.pack(">I", i), block, aad)
            out.write(struct.pack(">I", len(sealed)) + sealed)
            i += 1
            if last:
                break
    tmp.replace(dst)


def decrypt_file(src: Path, dst: Path, password: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with src.open("rb") as fin:
        head = fin.read(len(MAGIC) + 24)
        if not head.startswith(MAGIC) or len(head) != len(MAGIC) + 24:
            raise OffsiteError("ده مش ملف نسخة متشفّرة من MYTech")
        salt, prefix = head[len(MAGIC):len(MAGIC) + 16], head[len(MAGIC) + 16:]
        aes = AESGCM(_key(password, salt))
        tmp = dst.with_name(dst.name + ".partial")
        try:
            with tmp.open("wb") as out:
                i = 0
                while True:
                    raw = fin.read(4)
                    if len(raw) < 4:
                        raise OffsiteError("الملف ناقص (النسخة ماتنقلتش كلها)")
                    sealed = fin.read(struct.unpack(">I", raw)[0])
                    nonce = prefix + struct.pack(">I", i)
                    for last in (False, True):
                        try:
                            block = aes.decrypt(nonce, sealed, struct.pack(">I?", i, last))
                            break
                        except InvalidTag:
                            block = None
                    if block is None:
                        raise OffsiteError("كلمة السر غلط، أو الملف اتغيّر")
                    out.write(block)
                    i += 1
                    if last:
                        break
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    tmp.replace(dst)


# ---------------------------------------------------------------- settings
def _settings_path() -> Path:
    return Path(get_settings().backup_dir) / "offsite.json"


def _fernet():
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(b"mytech-offsite:" + get_settings().jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def load_config() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(cfg: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _password(cfg: dict) -> str:
    try:
        return _fernet().decrypt(cfg["password"].encode()).decode()
    except Exception:
        raise OffsiteError("كلمة سر النسخ مش مقروءة (الإعدادات اتغيرت): اكتبها تاني")


def configure(folder: str | None, password: str | None) -> dict:
    """folder None / "": turn the copy off. A new password is required to turn it on."""
    cfg = load_config()
    if not folder:
        cfg.pop("folder", None)
        cfg.pop("password", None)
        _save(cfg)
        return status()
    target = Path(folder)
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".mytech-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise OffsiteError(f"مش قادرين نكتب في الفولدر ده: {e.strerror or e}")
    if password:
        if len(password) < 8:
            raise OffsiteError("كلمة سر النسخ لازم ٨ حروف على الأقل")
        cfg["password"] = _fernet().encrypt(password.encode()).decode()
    elif "password" not in cfg:
        raise OffsiteError("لازم كلمة سر للنسخ")
    cfg["folder"] = str(target)
    _save(cfg)
    return status()


def status() -> dict:
    cfg = load_config()
    return {"folder": cfg.get("folder"), "enabled": bool(cfg.get("folder") and cfg.get("password")),
            "last": cfg.get("last")}


def _record(ok: bool, **info) -> None:
    cfg = load_config()
    cfg["last"] = {"ok": ok, "at": datetime.now(timezone.utc).isoformat(), **info}
    _save(cfg)


# ---------------------------------------------------------------- copying
def copy_backup(dump: Path) -> Path | None:
    """Encrypt one backup (and the new pictures) into the outside folder. None when the copy is off."""
    cfg = load_config()
    if not (cfg.get("folder") and cfg.get("password")):
        return None
    try:
        password = _password(cfg)
        folder = Path(cfg["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / (dump.stem + EXT)
        encrypt_file(dump, out, password)
        meta = dump.with_suffix(".json")
        if meta.exists():                       # file name, size, version, hash: nothing personal
            (folder / meta.name).write_bytes(meta.read_bytes())
        pictures = _copy_media(Path(get_settings().media_dir), folder / "media", password)
        _prune(folder, dump)
    except (OSError, OffsiteError) as e:
        msg = str(e) if isinstance(e, OffsiteError) else (e.strerror or type(e).__name__)
        _record(False, error=msg[:300], file=dump.name)
        log.error("outside backup copy failed: %s", msg)
        raise OffsiteError(msg) from e
    _record(True, file=out.name, pictures=pictures)
    log.info("outside backup copy written %s", out.name)
    return out


def _copy_media(source: Path, target: Path, password: str) -> int:
    if not source.is_dir():
        return 0
    n = 0
    for f in source.rglob("*"):
        if not f.is_file():
            continue
        dest = target / f.relative_to(source)
        dest = dest.with_name(dest.name + EXT)
        if dest.exists():                       # picture names are content hashes: never changed
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        encrypt_file(f, dest, password)
        n += 1
    return n


def _prune(folder: Path, dump: Path) -> None:
    """Keep as many copies of this kind (daily / manual) as the backup folder keeps."""
    label = dump.stem.rsplit("_", 1)[-1]
    keep = max(get_settings().backup_keep, 1)
    for old in sorted(folder.glob(f"mytech_*_{label}{EXT}"), reverse=True)[keep:]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


# ---------------------------------------------------------------- is it still working?
def problems(now: datetime | None = None) -> list[str]:
    """What the admin must hear about: no backup for over a day and a half, or the outside copy failing."""
    from app.ops.backup import last_status, list_backups

    now = now or datetime.now(timezone.utc)
    out = []
    backups = list_backups()
    newest = max((datetime.fromisoformat(b["created_at"]) for b in backups if b.get("created_at")), default=None)
    if newest is None or (now - newest).total_seconds() > 36 * 3600:
        last = last_status() or {}
        why = f" ({last['error'][:120]})" if last.get("ok") is False and last.get("error") else ""
        out.append("مفيش نسخة احتياطية اتعملت من أكتر من يوم ونص" + why)
    st = status()
    if st["enabled"]:
        last = st.get("last") or {}
        at = datetime.fromisoformat(last["at"]) if last.get("at") else None
        if last.get("ok") is False:
            out.append("النسخة اللي برّه المصنع فشلت: " + str(last.get("error", ""))[:120])
        elif at is None or (now - at).total_seconds() > 36 * 3600:
            out.append("النسخة اللي برّه المصنع ماتعملتش من أكتر من يوم ونص")
    return out
