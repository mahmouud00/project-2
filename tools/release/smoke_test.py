"""Smoke test of the COMPILED server (catches what only breaks after Nuitka compilation).

    python tools/release/smoke_test.py --exe <mytech-server(.exe)> --config <dir with .env> --port 8000 [--fresh-db]

The .env must use APP_MODE=online (demo data needs subscriptions, no licence file). --fresh-db also writes the
.env and creates a new database (local runs; needs MYTECH_ADMIN_URL).
"""
import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--exe", required=True)
p.add_argument("--config", required=True)
p.add_argument("--port", type=int, default=8000)
p.add_argument("--fresh-db", action="store_true")
a = p.parse_args()
exe, cfg = a.exe, a.config
env = dict(os.environ, LANG="C.UTF-8", LC_ALL="C.UTF-8")
if a.fresh_db:
    root = Path(cfg).parent
    shutil.rmtree(root, ignore_errors=True)
    Path(cfg).mkdir(parents=True)
    subprocess.run(["psql", "-q", "postgresql://postgres:postgres@localhost/postgres", "-c",
                    "DROP DATABASE IF EXISTS mytech_full WITH (FORCE)"], check=False)
    (Path(cfg) / ".env").write_text(f"""APP_MODE=online
DATABASE_URL=postgresql+psycopg://full_app:fullapp1@localhost:5432/mytech_full
DATABASE_SYSTEM_URL=postgresql+psycopg://full_system:fullsys1@localhost:5432/mytech_full
DATABASE_OWNER_URL=postgresql+psycopg://full_owner:fullown1@localhost:5432/mytech_full
JWT_SECRET=compiled-full-test-secret-0123456789abcdef0123456789
MEDIA_DIR={root}/media
BACKUP_DIR={root}/backups
HTTP_PORT={a.port}
DISCOVERY_ENABLED=false
""")
    commands = (["init-db"], ["migrate"], ["demo"])
else:
    commands = (["migrate"], ["demo"])
for cmd in commands:
    r = subprocess.run([exe, *cmd], cwd=cfg, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, (cmd, r.stdout[-2000:], r.stderr[-3000:])
    print(cmd[0], "ok")
import socket
for _ in range(60):   # a stopped service must have released the port (never test an older server)
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", a.port)) != 0:
            break
    time.sleep(1)
else:
    raise SystemExit(f"port {a.port} is still in use by another server")
srv = subprocess.Popen([exe, "serve"], cwd=cfg, env=env, stdout=open(Path(cfg) / "smoke-serve.log", "w"), stderr=subprocess.STDOUT)
B = f"http://127.0.0.1:{a.port}/api/v1"
def call(method, path, body=None, token=None, raw=False):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        return data.decode() if raw else json.loads(data or b"null")
try:
    for _ in range(60):
        try: call("GET", "/system/health"); break
        except Exception: time.sleep(1)
    assert srv.poll() is None, f"serve exited with {srv.returncode}"
    tok = call("POST", "/auth/login", {"company_code": "DEMO", "username": "admin", "password": "Admin@12345", "device_key": "full-test"})["access_token"]
    checks = []
    def ok(name, fn):
        try: fn(); checks.append((name, "ok"))
        except Exception as e: checks.append((name, f"FAIL {e} {getattr(e, 'read', lambda: b'')()[:300]}"))
    q = call("GET", "/quotations", token=tok)["items"]
    wo = call("GET", "/work-orders", token=tok)["items"][0]
    inv = call("GET", "/invoices", token=tok)["items"][0]
    systems = call("GET", "/library/systems", token=tok)
    model = call("GET", f"/library/models?system_id={systems[0]['id']}", token=tok)[0]
    ok("me", lambda: call("GET", "/auth/me", token=tok))
    ok("company", lambda: call("GET", "/company", token=tok))
    ok("license", lambda: call("GET", "/system/license", token=tok))
    ok("quotation detail", lambda: call("GET", f"/quotations/{q[0]['id']}", token=tok))
    ok("calculate", lambda: call("POST", "/engine/calculate", {"model_id": model["id"], "opening_width_mm": "1505", "opening_height_mm": "1200"}, token=tok))
    ok("manufacturing", lambda: call("GET", f"/work-orders/{wo['id']}/manufacturing", token=tok))
    ok("invoice print", lambda: "@font-face" in call("GET", f"/invoices/{inv['id']}/print", token=tok, raw=True) or 1/0)
    ok("quotation print", lambda: call("GET", f"/quotations/{q[0]['id']}/print", token=tok, raw=True))
    ok("cut list print", lambda: call("GET", f"/work-orders/{wo['id']}/print/cut-list", token=tok, raw=True))
    ok("statement", lambda: call("GET", f"/customers/{wo['customer_id']}/statement", token=tok))
    ok("employees", lambda: call("GET", "/employees", token=tok))
    ok("profit", lambda: call("GET", "/finance/profit", token=tok))
    ok("audit", lambda: call("GET", "/audit-log", token=tok))
    ok("logo", lambda: call("GET", "/company/logo", token=tok, raw=False) if False else urllib.request.urlopen(urllib.request.Request(B + "/company/logo", headers={"Authorization": "Bearer " + tok})).read())
    vt = call("POST", "/auth/login", {"company_code": "__platform__", "username": "vendor", "password": "Vendor@12345", "device_key": "full-test-v"})["access_token"]
    ok("model check", lambda: call("POST", f"/library/models/{model['id']}/check", token=vt))
    ok("tests run", lambda: call("POST", f"/library/models/{model['id']}/tests/run", token=vt))
    ok("package export", lambda: urllib.request.urlopen(urllib.request.Request(B + "/library/packages/export", method="POST", data=b"{}", headers={"Content-Type": "application/json", "Authorization": "Bearer " + vt})).read())
    for n, r in checks: print(f"{n:18} {r}")
    assert all(r == "ok" for _, r in checks)
    print("FULL COMPILED TEST OK")
finally:
    srv.terminate(); srv.wait(10)
