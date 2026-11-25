"""the sales workflow: the sales manager confirms surveys and quotations; each salesperson's own work

Surveys and quotations get their confirmation; every existing one counts as confirmed (nothing waits after the
upgrade). Whoever may set the price (the sales manager, the administrator) may also confirm.
Collections (تحصيل) on an invoice: recorded by the salesperson, counted only once the accounts confirm them
(new table; the money already received stays as it is). Invoices get their own read permission: whoever could read
the treasury or make invoices keeps it; the built-in salesperson may now read and make his invoices and record what
he collects, and the accounts confirm.
Customers, surveys, quotations and invoices get their salesperson (owner_id), who is whoever made them. Every role
but the built-in salesperson keeps seeing everyone's work (sales.all); the sales manager may move work (sales.transfer).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-25 01:00:00
"""
from alembic import op
import sqlalchemy as sa

from app.db import rls

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None

APPROVAL_TABLES = ('site_surveys', 'quotations')
OWNED_TABLES = ('customers', 'site_surveys', 'quotations', 'invoices')


def _grant(perm: str, where: str) -> None:
    op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{perm}') "
               f"WHERE ({where}) AND NOT ('{perm}' = ANY(permissions))")


def upgrade() -> None:
    op.create_table('collections',
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=True),
    sa.Column('amount', sa.Numeric(14, 2), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=100), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('reject_reason', sa.Text(), nullable=False),
    sa.Column('cash_transaction_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False), sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True), sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_collections_company_id_companies')),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], name=op.f('fk_collections_invoice_id_invoices')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_collections_customer_id_customers')),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name=op.f('fk_collections_branch_id_branches')),
    sa.ForeignKeyConstraint(['cash_transaction_id'], ['cash_transactions.id'],
                            name=op.f('fk_collections_cash_transaction_id_cash_transactions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collections')))
    for c in ('company_id', 'invoice_id', 'customer_id', 'branch_id', 'owner_id'):
        op.create_index(op.f(f'ix_collections_{c}'), 'collections', [c])
    rls.enable(op, "collections")
    _grant('invoices.read', "'treasury.read' = ANY(permissions) OR 'invoices.create' = ANY(permissions) "
                            "OR (is_builtin AND code IN ('sales', 'sales_manager', 'admin'))")
    _grant('invoices.create', "is_builtin AND code = 'sales'")
    _grant('collections.create', "'treasury.create' = ANY(permissions) OR 'invoices.create' = ANY(permissions) "
                                 "OR (is_builtin AND code IN ('sales', 'sales_manager', 'admin'))")
    _grant('collections.confirm', "'treasury.create' = ANY(permissions) OR (is_builtin AND code = 'admin')")
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
    for perm in ('invoices.read', 'collections.create', 'collections.confirm'):
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'invoices.create') WHERE is_builtin AND code = 'sales'")
    op.drop_table('collections')
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
