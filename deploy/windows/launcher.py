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


def kill_with_launcher(proc: subprocess.Popen) -> None:
    """Put the server in a Windows job that is closed when this launcher exits (even when the service
    manager kills it), so stopping the service never leaves an old server holding the port."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job = k32.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
        and k32.AssignProcessToJobObject(job, int(proc._handle))
    if not ok:
        print(f"launcher: job object not available (error {ctypes.get_last_error()})", file=sys.stderr)
    globals()["_job"] = job   # the handle stays open for the launcher's lifetime


def main() -> int:
    root = root_dir()
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    version_dir = root / current["path"]
    config_dir = root / "config"
    exe = version_dir / "mytech-server.exe"
    if exe.exists():
        env = dict(os.environ, MYTECH_ROOT=str(root))
        proc = subprocess.Popen([str(exe), "serve"], cwd=str(config_dir), env=env)
        kill_with_launcher(proc)
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
