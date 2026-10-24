"""Row-Level Security DDL used by migrations.

tenant  : a company sees only its rows.
library : a company sees its rows + the platform library rows; writes only its own.
"""
from __future__ import annotations

PLATFORM = "00000000-0000-0000-0000-000000000001"
CURRENT = "NULLIF(current_setting('app.company_id', true), '')::uuid"


def policy_sql(table: str, tenancy: str = "tenant") -> list[str]:
    key = "id" if table == "companies" else "company_id"
    if tenancy == "library":
        using = f"({key} = {CURRENT} OR {key} = '{PLATFORM}'::uuid)"
    else:
        using = f"({key} = {CURRENT})"
    check = f"({key} = {CURRENT})"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
        f"CREATE POLICY tenant_isolation ON {table} USING {using} WITH CHECK {check}",
    ]


def enable(op, table: str, tenancy: str = "tenant") -> None:
    for stmt in policy_sql(table, tenancy):
        op.execute(stmt)
