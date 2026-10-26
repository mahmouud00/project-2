"""separate add (create) and delete permissions per section

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

# nobody loses what they could do: whoever could edit a section (or create through another permission)
# can still add to it; the delete permissions go to the built-in administrator role only
GRANTS = [
    ("customers.write", "customers.create"), ("surveys.write", "surveys.create"), ("quotes.write", "quotes.create"),
    ("workorders.write", "workorders.create"), ("inventory.write", "inventory.create"),
    ("purchasing.write", "purchasing.create"), ("treasury.write", "treasury.create"),
    ("treasury.write", "invoices.create"), ("pricelists.manage", "pricelists.create"),
    ("org.manage", "inventory.create"), ("org.manage", "treasury.create"),      # warehouses and cashboxes
]
ADMIN_ONLY = ["library.delete", "customers.delete", "surveys.delete", "quotes.delete", "pricelists.delete", "workorders.delete",
              "invoices.delete", "inventory.delete", "purchasing.delete", "treasury.delete"]


def _add(perm: str, where: str) -> None:
    op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{perm}') "
               f"WHERE {where} AND NOT ('{perm}' = ANY(permissions))")


def upgrade() -> None:
    for have, add in GRANTS:
        _add(add, f"'{have}' = ANY(permissions)")
    for perm in ADMIN_ONLY + [add for _, add in GRANTS]:
        _add(perm, "code = 'admin' AND is_builtin")


def downgrade() -> None:
    for perm in set(ADMIN_ONLY) | {add for _, add in GRANTS}:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")
