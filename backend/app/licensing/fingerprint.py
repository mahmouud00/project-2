"""Server machine fingerprint for offline licences."""
from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path


def _windows_parts() -> list[str]:
    parts = []
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            parts.append(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        pass
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_BaseBoard).SerialNumber"],
                             capture_output=True, text=True, timeout=10)
        if out.stdout.strip():
            parts.append(out.stdout.strip())
    except Exception:
        pass
    return parts


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
