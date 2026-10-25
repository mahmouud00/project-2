"""MYTech Licence Tool (vendor only, never shipped to customers).

Windows build: compiled to MYTech-License-Tool.exe (see tools/release/build_license_tool.py).
    python -m tools.vendor_admin.gui

- Issue a licence for a customer server (machine fingerprint + modules + limits + expiry), signed with
  the MYTech private key (Ed25519). The server only accepts licences signed by this key.
- Verify a licence file.
- Sign a library update package exported from the library screen.
- Generate a new key pair / change the private key passphrase.
The private key file stays encrypted on disk; it is decrypted in memory only while the tool runs.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
import tkinter as tk

ROOT = Path(__file__).resolve().parents[2]
if (ROOT / "backend").exists():
    sys.path.insert(0, str(ROOT / "backend"))

from app.licensing.modules import MODULES  # noqa: E402
from tools.vendor_admin.licenses import build_license  # noqa: E402
from app.licensing.signing import (generate_keypair, load_private_key, load_public_key, public_key_module,  # noqa: E402
                                   reencrypt_private_key, sign_document, verify_document)

APP_TITLE = "MYTech Licence Tool"
MODULE_LABELS = {"core": "Core (sales, customers, treasury, inventory)", "manufacturing": "Manufacturing",
                 "mfg.upvc": "UPVC", "mfg.shutter": "Shutter", "mfg.aluminum": "Aluminium"}
BRAND = "#5048E5"


def ask_password(parent, title: str, prompt: str, confirm: bool = False) -> str | None:
    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()
    v1, v2 = StringVar(), StringVar()
    ttk.Label(win, text=prompt).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 6), sticky="w")
    e1 = ttk.Entry(win, textvariable=v1, show="•", width=40)
    e1.grid(row=1, column=0, columnspan=2, padx=14, sticky="we")
    if confirm:
        ttk.Label(win, text="Repeat:").grid(row=2, column=0, columnspan=2, padx=14, pady=(8, 2), sticky="w")
        ttk.Entry(win, textvariable=v2, show="•", width=40).grid(row=3, column=0, columnspan=2, padx=14, sticky="we")
    result: dict = {}

    def ok(*_):
        if confirm and v1.get() != v2.get():
            messagebox.showerror(title, "The two passphrases are different.", parent=win)
            return
        if confirm and len(v1.get()) < 10:
            messagebox.showerror(title, "Use at least 10 characters.", parent=win)
            return
        result["v"] = v1.get()
        win.destroy()

    bar = ttk.Frame(win)
    bar.grid(row=4, column=0, columnspan=2, pady=14)
    ttk.Button(bar, text="OK", command=ok).pack(side="left", padx=4)
    ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="left", padx=4)
    e1.focus_set()
    win.bind("<Return>", ok)
    parent.wait_window(win)
    return result.get("v")


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.key = None            # decrypted private key (memory only)
        self.key_path = StringVar(value="No private key loaded")
        root.title(APP_TITLE)
        root.geometry("820x640")
        root.minsize(760, 580)
        style = ttk.Style(root)
        try:
            style.theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground=BRAND)
        style.configure("Ok.TLabel", foreground="#15803D")
        style.configure("Bad.TLabel", foreground="#C62828")

        head = ttk.Frame(root, padding=(14, 12, 14, 4))
        head.pack(fill="x")
        ttk.Label(head, text="MYTech Solutions — Licence Tool", style="Title.TLabel").pack(side="left")
        keybar = ttk.Frame(root, padding=(14, 2, 14, 8))
        keybar.pack(fill="x")
        ttk.Label(keybar, text="Signing key:").pack(side="left")
        self.key_label = ttk.Label(keybar, textvariable=self.key_path, style="Bad.TLabel")
        self.key_label.pack(side="left", padx=6)
        ttk.Button(keybar, text="Load private key…", command=self.load_key).pack(side="right")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        nb.add(self.issue_tab(nb), text="  Issue licence  ")
        nb.add(self.verify_tab(nb), text="  Verify licence  ")
        nb.add(self.package_tab(nb), text="  Sign library package  ")
        nb.add(self.update_tab(nb), text="  Sign server update  ")
        nb.add(self.keys_tab(nb), text="  Keys  ")

    # ------------------------------------------------------------------ key
    def load_key(self):
        path = filedialog.askopenfilename(title="MYTech private key", filetypes=[("PEM key", "*.pem"), ("All files", "*.*")])
        if not path:
            return
        pem = Path(path).read_bytes()
        password = None
        if b"ENCRYPTED" in pem:
            password = ask_password(self.root, APP_TITLE, "Passphrase of the private key:")
            if password is None:
                return
        try:
            key = load_private_key(pem, password.encode() if password else None)
        except Exception:
            messagebox.showerror(APP_TITLE, "Wrong passphrase or not a MYTech private key.")
            return
        self.key = key
        matches = self._matches_shipped(key)
        self.key_path.set(f"{Path(path).name} — " + ("matches the key compiled into the server ✓" if matches
                                                     else "WARNING: does not match the key compiled into this build"))
        self.key_label.configure(style="Ok.TLabel" if matches else "Bad.TLabel")

    @staticmethod
    def _matches_shipped(key) -> bool:
        from cryptography.hazmat.primitives import serialization
        mine = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        shipped = load_public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return mine == shipped

    def need_key(self) -> bool:
        if self.key is None:
            messagebox.showwarning(APP_TITLE, "Load the MYTech private key first (top right).")
            return False
        return True

    # ------------------------------------------------------------------ issue
    def issue_tab(self, nb):
        f = ttk.Frame(nb, padding=14)
        self.v = {k: StringVar() for k in ("code", "name", "fingerprint", "devices", "users", "branches", "expires", "grace", "notes")}
        self.v["devices"].set("5")
        self.v["grace"].set("14")
        self.v["expires"].set(date(date.today().year + 1, date.today().month, min(date.today().day, 28)).isoformat())
        rows = [("Company code", "code", 20), ("Company name", "name", 50), ("Server fingerprint", "fingerprint", 70),
                ("Max devices", "devices", 8), ("Max users (empty = no limit)", "users", 8),
                ("Max branches (empty = no limit)", "branches", 8), ("Expires (YYYY-MM-DD, empty = perpetual)", "expires", 14),
                ("Grace days after expiry", "grace", 8), ("Notes", "notes", 60)]
        for i, (label, key, width) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(f, textvariable=self.v[key], width=width).grid(row=i, column=1, sticky="w", pady=4)
        ttk.Label(f, text="Modules").grid(row=len(rows), column=0, sticky="nw", pady=6)
        box = ttk.Frame(f)
        box.grid(row=len(rows), column=1, sticky="w", pady=6)
        self.mods = {m: BooleanVar(value=m in ("core", "manufacturing", "mfg.upvc")) for m in MODULES}
        for m, var in self.mods.items():
            cb = ttk.Checkbutton(box, text=MODULE_LABELS.get(m, m), variable=var)
            if m == "core":
                cb.state(["disabled"])
            cb.pack(anchor="w")
        ttk.Button(f, text="Create licence file…", command=self.issue).grid(row=len(rows) + 1, column=1, sticky="w", pady=14)
        ttk.Label(f, text="The fingerprint is shown on the customer server (licence screen, or `mytech-server fingerprint`).",
                  foreground="#6A7686").grid(row=len(rows) + 2, column=0, columnspan=2, sticky="w")
        return f

    def issue(self):
        if not self.need_key():
            return
        v = {k: s.get().strip() for k, s in self.v.items()}
        try:
            if not v["code"] or not v["name"] or len(v["fingerprint"]) < 16:
                raise ValueError("Company code, name and the server fingerprint are required.")
            mods = [m for m, var in self.mods.items() if var.get() or m == "core"]
            if any(m.startswith("mfg.") for m in mods) and "manufacturing" not in mods:
                mods.append("manufacturing")
            expires = None
            if v["expires"]:
                d = datetime.fromisoformat(v["expires"])
                expires = d.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc).isoformat()
            num = lambda s: int(s) if s else None  # noqa: E731
            payload = build_license(company_code=v["code"], company_name=v["name"], fingerprint=v["fingerprint"], modules=mods,
                                    max_devices=int(v["devices"]), max_users=num(v["users"]), max_branches=num(v["branches"]),
                                    expires=expires, grace_days=int(v["grace"] or 14), notes=v["notes"])
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        doc = sign_document(self.key, payload)
        out = filedialog.asksaveasfilename(title="Save licence", defaultextension=".json",
                                           initialfile=f"license-{v['code']}.json", filetypes=[("Licence", "*.json")])
        if not out:
            return
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo(APP_TITLE, f"Licence {payload['license_id']} saved.\n\nThe customer installs it from the licence screen "
                                       "of the program (or copies it to C:\\MYTech\\license\\license.json).")

    # ------------------------------------------------------------------ verify
    def verify_tab(self, nb):
        f = ttk.Frame(nb, padding=14)
        ttk.Button(f, text="Open licence file…", command=self.verify).pack(anchor="w")
        self.verify_status = ttk.Label(f, text="")
        self.verify_status.pack(anchor="w", pady=8)
        self.verify_text = tk.Text(f, height=24, wrap="word", font=("Consolas", 10))
        self.verify_text.pack(fill="both", expand=True)
        return f

    def verify(self):
        path = filedialog.askopenfilename(title="Licence file", filetypes=[("Licence", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            messagebox.showerror(APP_TITLE, "Not a licence file.")
            return
        ok = verify_document(doc)
        self.verify_status.configure(text="Signature VALID (signed with the MYTech key)" if ok else "Signature INVALID",
                                     style="Ok.TLabel" if ok else "Bad.TLabel")
        self.verify_text.delete("1.0", "end")
        self.verify_text.insert("1.0", json.dumps(doc.get("payload"), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------ packages
    def package_tab(self, nb):
        f = ttk.Frame(nb, padding=14)
        ttk.Label(f, text="Export the package from the library screen (MYTech account → Library → Update packages),\n"
                          "sign it here, then send the signed file to customers.").pack(anchor="w")
        ttk.Button(f, text="Sign package…", command=self.sign_package).pack(anchor="w", pady=12)
        self.pkg_status = ttk.Label(f, text="")
        self.pkg_status.pack(anchor="w")
        return f

    def sign_package(self):
        if not self.need_key():
            return
        path = filedialog.askopenfilename(title="Library package", filetypes=[("Package", "*.zip"), ("All files", "*.*")])
        if not path:
            return
        from app.licensing.packaging import sign_package
        try:
            signed = sign_package(Path(path).read_bytes(), self.key)
        except Exception as e:  # noqa: BLE001 - shown to the vendor
            messagebox.showerror(APP_TITLE, f"Could not sign: {e}")
            return
        out = filedialog.asksaveasfilename(title="Save signed package", defaultextension=".zip",
                                           initialfile=Path(path).stem.replace(".unsigned", "") + ".signed.zip")
        if not out:
            return
        Path(out).write_bytes(signed)
        doc = json.loads(zipfile.ZipFile(io.BytesIO(signed)).read("package.json"))
        systems = ", ".join(s["system"]["code"] for s in doc["payload"]["systems"])
        self.pkg_status.configure(text=f"Signed {doc['payload']['package_id']}  ({systems})", style="Ok.TLabel")

    # ------------------------------------------------------------------ server updates
    def update_tab(self, nb):
        f = ttk.Frame(nb, padding=14)
        ttk.Label(f, text="Turns MYTech-Server-Update-Payload-<version>.zip (from the release) into a signed update file\n"
                          "(mytech-<version>.mtu). Customers apply it with update.ps1; it backs up first and rolls back on failure.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.upd = {k: StringVar() for k in ("min_from", "min_client", "notes")}
        self.upd["min_from"].set("0.0.0")
        self.upd["min_client"].set("0.0.0")
        for i, (label, key) in enumerate([("Customers must have at least version", "min_from"),
                                          ("Oldest desktop program allowed", "min_client"), ("Release notes", "notes")], 1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(f, textvariable=self.upd[key], width=50 if key == "notes" else 12).grid(row=i, column=1, sticky="w", pady=4)
        ttk.Button(f, text="Choose payload zip and sign…", command=self.sign_update).grid(row=4, column=1, sticky="w", pady=12)
        self.upd_status = ttk.Label(f, text="")
        self.upd_status.grid(row=5, column=0, columnspan=2, sticky="w")
        return f

    def sign_update(self):
        if not self.need_key():
            return
        path = filedialog.askopenfilename(title="Server update payload", filetypes=[("Payload", "*.zip")])
        if not path:
            return
        import tempfile
        from app.ops.updater import build_package
        with tempfile.TemporaryDirectory() as tmp:
            try:
                zipfile.ZipFile(path).extractall(tmp)
                version = (Path(tmp) / "VERSION").read_text(encoding="utf-8").strip()
                if not (Path(tmp) / "mytech-server.exe").exists():
                    raise ValueError("This zip is not a compiled server payload (mytech-server.exe missing).")
                data = build_package(Path(tmp), version, self.key, min_from_version=self.upd["min_from"].get().strip() or "0.0.0",
                                     min_client_version=self.upd["min_client"].get().strip() or "0.0.0",
                                     notes=self.upd["notes"].get().strip())
            except (OSError, ValueError, zipfile.BadZipFile) as e:
                messagebox.showerror(APP_TITLE, str(e))
                return
        out = filedialog.asksaveasfilename(title="Save update file", defaultextension=".mtu", initialfile=f"mytech-{version}.mtu")
        if not out:
            return
        Path(out).write_bytes(data)
        self.upd_status.configure(text=f"Signed update {version} ({len(data) // 1048576} MB)", style="Ok.TLabel")

    # ------------------------------------------------------------------ keys
    def keys_tab(self, nb):
        f = ttk.Frame(nb, padding=14)
        ttk.Label(f, text="Change passphrase: re-encrypts the loaded private key file with a new passphrase.").pack(anchor="w")
        ttk.Button(f, text="Change passphrase…", command=self.change_passphrase).pack(anchor="w", pady=(4, 18))
        ttk.Label(f, text="Generate a NEW key pair (only when replacing the MYTech key). Licences signed with the new key\n"
                          "work only on servers built with its public key: put the generated vendor_key.py in\n"
                          "backend/app/licensing/ and rebuild the server.", foreground="#C62828").pack(anchor="w")
        ttk.Button(f, text="Generate new key pair…", command=self.keygen).pack(anchor="w", pady=4)
        return f

    def change_passphrase(self):
        path = filedialog.askopenfilename(title="Private key to re-encrypt", filetypes=[("PEM key", "*.pem")])
        if not path:
            return
        pem = Path(path).read_bytes()
        old = ask_password(self.root, APP_TITLE, "Current passphrase:") if b"ENCRYPTED" in pem else ""
        if old is None:
            return
        new = ask_password(self.root, APP_TITLE, "New passphrase:", confirm=True)
        if not new:
            return
        try:
            out = reencrypt_private_key(pem, old.encode() if old else None, new.encode())
        except Exception:
            messagebox.showerror(APP_TITLE, "Wrong current passphrase.")
            return
        Path(path).write_bytes(out)
        messagebox.showinfo(APP_TITLE, "Passphrase changed. Keep a backup of the key file in a safe place.")

    def keygen(self):
        if not messagebox.askyesno(APP_TITLE, "Create a NEW MYTech key pair?\n\nExisting customer licences keep working only "
                                              "with servers built with the old key."):
            return
        pw = ask_password(self.root, APP_TITLE, "Passphrase for the new private key:", confirm=True)
        if not pw:
            return
        out = filedialog.asksaveasfilename(title="Save the new PRIVATE key", defaultextension=".pem",
                                           initialfile="mytech-vendor-private-key.pem")
        if not out:
            return
        priv, pub = generate_keypair(pw.encode())
        Path(out).write_bytes(priv)
        pub_out = Path(out).with_name("vendor_key.py")
        pub_out.write_text(public_key_module(pub), encoding="utf-8")
        messagebox.showinfo(APP_TITLE, f"Private key: {out}\nPublic key module: {pub_out}\n\nBack up the private key; "
                                       "it can not be recovered. Never send it to anyone.")


def selftest() -> int:
    """Used by the release build on the compiled exe: window + issue + verify with a throw-away key."""
    root = Tk()
    root.withdraw()
    app = App(root)
    priv, pub = generate_keypair(b"selftest-passphrase")
    key = load_private_key(priv, b"selftest-passphrase")
    payload = build_license(company_code="SELFTEST", company_name="اختبار", fingerprint="0" * 64, modules=["core"],
                            max_devices=1)
    doc = sign_document(key, payload)
    assert verify_document(doc, load_public_key(pub)) and not verify_document(doc)  # shipped key must not accept it
    assert app._matches_shipped(key) is False
    load_public_key()
    root.destroy()
    if sys.stdout:  # the GUI build has no console
        print("selftest ok")
    return 0


def _error_log() -> Path:
    import os
    import tempfile
    return Path(os.environ.get("MYTECH_TOOL_LOG") or Path(tempfile.gettempdir()) / "mytech-license-tool-error.log")


def main() -> int:
    try:
        if "--selftest" in sys.argv:
            return selftest()
        root = Tk()
        App(root)
        root.mainloop()
        return 0
    except Exception:  # noqa: BLE001 - a GUI without a console must still report why it stopped
        import traceback
        _error_log().write_text(traceback.format_exc(), encoding="utf-8")
        if "--selftest" not in sys.argv:
            try:
                messagebox.showerror(APP_TITLE, f"Unexpected error. Details: {_error_log()}")
            except Exception:  # noqa: BLE001
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
