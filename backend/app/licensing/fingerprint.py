"""Server machine fingerprint for offline licences."""
from __future__ import annotations

import hashlib
import platform
from pathlib import Path


def _windows_parts() -> list[str]:
    """Registry values only (no subprocess, no WMI): identical for the installer (Administrator) and the
    service (LocalSystem), and never slow at service start, so a valid licence can't be lost to a timeout.
    MachineGuid is unique per Windows installation; the BIOS values tie it to the board model."""
    import winreg  # type: ignore

    parts = []
    values = [(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid")] + [
        (r"HARDWARE\DESCRIPTION\System\BIOS", name)
        for name in ("SystemManufacturer", "SystemProductName", "BaseBoardManufacturer", "BaseBoardProduct")]
    for path, name in values:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                value = str(winreg.QueryValueEx(key, name)[0]).strip()
        except OSError:
            value = ""
        parts.append(value)
    return parts if parts[0] else []


def _linux_parts() -> list[str]:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        p = Path(path)
        if p.exists():
            return [p.read_text().strip()]
    return []


def machine_fingerprint() -> str:
    parts = _windows_parts() if platform.system() == "Windows" else _linux_parts()
    if not parts:
        parts = [platform.node()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
