"""sales guide prices instead of price lists; the sales manager approves a price under the fair price

Price lists are no longer used: the salesperson types the price, with the fair price (cost + 20 %) and the top
price (cost + 30 %) as a guide. Lists and the quotations that point to them stay as they were (the column becomes
optional for new quotations). Existing quotations keep their prices and need no approval (fair total 0).
The built-in administrator and sales manager roles may approve a price under the fair price; the price-list
permissions are removed.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

APPROVE = "quotes.approve_price"
PRICE_LISTS = ("pricelists.create", "pricelists.manage", "pricelists.delete")


def upgrade() -> None:
    op.alter_column('quotations', 'price_list_id', existing_type=sa.UUID(), nullable=True)
    op.add_column('quotations', sa.Column('fair_total', sa.Numeric(14, 2), server_default='0', nullable=False))
    op.add_column('quotations', sa.Column('top_total', sa.Numeric(14, 2), server_default='0', nullable=False))
    op.add_column('quotations', sa.Column('price_approved_total', sa.Numeric(14, 2), nullable=True))
    op.add_column('quotations', sa.Column('price_approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('quotations', sa.Column('price_approved_by', sa.UUID(), nullable=True))
    op.add_column('quotations', sa.Column('price_approval_note', sa.Text(), server_default='', nullable=False))
    op.execute(f"UPDATE roles SET permissions = array_append(permissions, '{APPROVE}') "
               f"WHERE is_builtin AND code IN ('admin', 'sales_manager') AND NOT ('{APPROVE}' = ANY(permissions))")
    for perm in PRICE_LISTS:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{perm}')")


def downgrade() -> None:
    op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{APPROVE}')")
    op.execute("UPDATE roles SET permissions = permissions || ARRAY['pricelists.create', 'pricelists.manage', "
               "'pricelists.delete'] WHERE is_builtin AND code = 'admin'")
    for col in ('price_approval_note', 'price_approved_by', 'price_approved_at', 'price_approved_total',
                'top_total', 'fair_total'):
        op.drop_column('quotations', col)
    # the price list stays optional: quotations made without one are kept
