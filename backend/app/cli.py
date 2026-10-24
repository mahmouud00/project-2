"""Server administration CLI.

    python -m app.cli init-db --admin-url postgresql+psycopg://postgres:***@localhost/postgres
    python -m app.cli migrate
    python -m app.cli create-company --code ACME --name "..." --admin admin --password ...
    python -m app.cli create-platform-admin --username vendor --password ...
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def init_db(admin_url: str) -> None:
    """Create the three roles and the database (idempotent). Needs a superuser."""
    s = get_settings()
    owner, app, system = (make_url(u) for u in (s.database_owner_url, s.database_url, s.database_system_url))
    dbname = owner.database
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        # owner: migrations, backups, restores and data migrations must see every company
        for url, extra in ((owner, "BYPASSRLS"), (app, "NOBYPASSRLS"), (system, "BYPASSRLS")):
            exists = c.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": url.username})
            verb = "ALTER" if exists else "CREATE"
            c.execute(text(f"{verb} ROLE {_quote_ident(url.username)} LOGIN {extra} "
                           f"PASSWORD {_quote_lit(url.password or '')}"))
        # the owner stops API sessions before a restore
        c.execute(text(f"GRANT pg_signal_backend TO {_quote_ident(owner.username)}"))
        if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": dbname}):
            c.execute(text(f"CREATE DATABASE {_quote_ident(dbname)} OWNER {_quote_ident(owner.username)} "
                           f"ENCODING 'UTF8' TEMPLATE template0"))
    engine.dispose()
    db_engine = create_engine(admin_url.rsplit("/", 1)[0] + "/" + dbname, isolation_level="AUTOCOMMIT")
    with db_engine.connect() as c:
        o = _quote_ident(owner.username)
        c.execute(text(f"ALTER SCHEMA public OWNER TO {o}"))
        for role in (app.username, system.username):
            r = _quote_ident(role)
            c.execute(text(f"GRANT CONNECT ON DATABASE {_quote_ident(dbname)} TO {r}"))
            c.execute(text(f"GRANT USAGE ON SCHEMA public TO {r}"))
            c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {r}"))
            c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {r}"))
            c.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public "
                           f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {r}"))
            c.execute(text(f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public "
                           f"GRANT USAGE, SELECT ON SEQUENCES TO {r}"))
    db_engine.dispose()


def migrate(url: str | None = None, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    if url:
        cfg.attributes["url"] = url
    command.upgrade(cfg, revision)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mytech")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-db")
    p.add_argument("--admin-url", default=os.environ.get("MYTECH_ADMIN_URL"),
                   help="superuser URL (or env MYTECH_ADMIN_URL, so it never shows on a command line)")
    sub.add_parser("migrate")
    p = sub.add_parser("create-company")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--admin", default="admin")
    p.add_argument("--password")
    p = sub.add_parser("create-platform-admin")
    p.add_argument("--username", required=True)
    p.add_argument("--password")
    sub.add_parser("demo", help="create the demo companies and example data (APP_MODE=online)")
    sub.add_parser("serve", help="run the API server")
    sub.add_parser("version", help="print the server version")
    sub.add_parser("fingerprint", help="print this machine's fingerprint (offline licence request)")
    p = sub.add_parser("backup", help="back up the database now")
    p.add_argument("--label", default="manual")
    p = sub.add_parser("restore", help="restore a backup file (stops nothing: stop the service first)")
    p.add_argument("file")
    p = sub.add_parser("update", help="apply a signed update file (*.mtu)")
    p.add_argument("package")
    p.add_argument("--root", default=os.environ.get("MYTECH_ROOT", "C:\\MYTech"))
    p.add_argument("--service", default="MYTechServer")
    p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.cmd == "init-db":
        if not args.admin_url:
            parser.error("init-db needs --admin-url or MYTECH_ADMIN_URL")
        init_db(args.admin_url)
    elif args.cmd == "migrate":
        migrate()
    elif args.cmd == "demo":
        from app.demo import setup_demo
        print("demo data created" if setup_demo() else "demo data already exists")
    elif args.cmd == "serve":
        from app.server import serve
        serve()
    elif args.cmd == "version":
        from app.core.config import read_version
        print(read_version())
    elif args.cmd == "fingerprint":
        from app.licensing.fingerprint import machine_fingerprint
        print(machine_fingerprint())
    elif args.cmd == "backup":
        from app.ops.backup import run_backup, verify
        print(json.dumps(verify(run_backup(args.label)), ensure_ascii=False))
    elif args.cmd == "restore":
        from pathlib import Path
        from app.ops.backup import restore
        print(json.dumps(restore(Path(args.file)), ensure_ascii=False, default=str))
    elif args.cmd == "update":
        from app.ops.updater import main as update_main
        return update_main([args.package, "--root", args.root, "--service", args.service, "--port", str(args.port)])
    elif args.cmd in ("create-company", "create-platform-admin"):
        from app.db import models  # noqa: F401
        from app.db.session import system_session
        from app.modules.org.service import create_company, create_platform_admin

        # unattended installs pass the password in the environment, never on the command line
        password = args.password or os.environ.get("MYTECH_NEW_PASSWORD") or getpass.getpass("Password: ")
        with system_session() as db:
            if args.cmd == "create-company":
                company, _ = create_company(db, code=args.code, name=args.name, admin_username=args.admin,
                                            admin_password=password)
                print(f"company {company.code} id={company.id}")
            else:
                user = create_platform_admin(db, args.username, password)
                print(f"platform admin {user.username}")
            db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
