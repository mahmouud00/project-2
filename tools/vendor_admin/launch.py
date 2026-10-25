"""Entry point of MYTech-License-Tool.exe: imports the GUI inside the error handler, so a failure while
loading (not only while running) is written to the log and shown, instead of a silent exit."""
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _log_path() -> Path:
    return Path(os.environ.get("MYTECH_TOOL_LOG") or Path(tempfile.gettempdir()) / "mytech-license-tool-error.log")


def run() -> int:
    try:
        from tools.vendor_admin.gui import main
        return main()
    except BaseException as exc:  # noqa: BLE001 - last line of defence for a console-less program
        if isinstance(exc, SystemExit):
            raise
        _log_path().write_text(traceback.format_exc(), encoding="utf-8")
        try:
            from tkinter import messagebox
            messagebox.showerror("MYTech Licence Tool", f"The tool could not start. Details: {_log_path()}")
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(run())
