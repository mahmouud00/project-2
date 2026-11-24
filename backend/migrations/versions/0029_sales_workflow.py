"""the sales workflow: the sales manager confirms surveys and quotations; each salesperson's own work

Surveys and quotations get their confirmation; every existing one counts as confirmed (nothing waits after the
upgrade). Whoever may set the price (the sales manager, the administrator) may also confirm.
Customers, surveys, quotations and invoices get their salesperson (owner_id), who is whoever made them. Every role
but the built-in salesperson keeps seeing everyone's work (sales.all); the sales manager may move work (sales.transfer).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-25 01:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None

APPROVAL_TABLES = ('site_surveys', 'quotations')
OWNED_TABLES = ('customers', 'site_surveys', 'quotations', 'invoices')


def upgrade() -> None:
    for table in APPROVAL_TABLES:
        op.add_column(table, sa.Column('approval_status', sa.String(length=12), server_default='approved', nullable=False))
        op.add_column(table, sa.Column('approval_requested_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column('approved_by', sa.UUID(), nullable=True))
    for table in OWNED_TABLES:
        op.add_column(table, sa.Column('owner_id', sa.UUID(), nullable=True))
        op.create_index(op.f(f'ix_{table}_owner_id'), table, ['owner_id'])
        op.execute(f"UPDATE {table} SET owner_id = created_by")
    op.execute("UPDATE roles SET permissions = array_append(permissions, 'sales.all') "
               "WHERE NOT (is_builtin AND code = 'sales') AND NOT ('sales.all' = ANY(permissions)) AND "
               "permissions && ARRAY['customers.read', 'surveys.read', 'quotes.read', 'treasury.read']::varchar[]")
    op.execute("UPDATE roles SET permissions = array_append(permissions, 'sales.transfer') "
               "WHERE ('quotes.approve_price' = ANY(permissions) OR (is_builtin AND code = 'admin')) "
               "AND NOT ('sales.transfer' = ANY(permissions))")
    for perm in ('surveys.approve', 'quotes.approve'):
        op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{perm}') "
                   f"WHERE ('quotes.approve_price' = ANY(permissions) OR (is_builtin AND code = 'admin')) "
                   f"AND NOT ('{perm}' = ANY(permissions))")


def downgrade() -> None:
    for perm in ('sales.all', 'sales.transfer'):
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")
    for table in OWNED_TABLES:
        op.drop_index(op.f(f'ix_{table}_owner_id'), table_name=table)
        op.drop_column(table, 'owner_id')
    for perm in ('surveys.approve', 'quotes.approve'):
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")
    for table in APPROVAL_TABLES:
        for col in ('approved_by', 'approved_at', 'approval_requested_at', 'approval_status'):
            op.drop_column(table, col)
