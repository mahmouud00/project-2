"""what a customer must have (the governorate, how they reached us, how the talk started, their questions), and
automatic quotation pricing (one margin, one price per m², discounts by the sales manager)

New empty columns on customers: old customers are completed when they are next edited. Quotations get the pricing
mode: every existing quotation is "manual" (its prices stay as they are); new ones are automatic.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-24 16:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('governorate', sa.String(length=40), nullable=True))
    op.add_column('customers', sa.Column('contact_method', sa.String(length=30), nullable=True))
    op.add_column('customers', sa.Column('first_contact', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('customer_questions', sa.Text(), nullable=True))
    op.add_column('quotations', sa.Column('pricing_mode', sa.String(length=10), server_default='manual', nullable=False))
    op.add_column('quotations', sa.Column('auto_price_per_m2', sa.Numeric(14, 2), nullable=True))
    op.add_column('quotations', sa.Column('manager_price_per_m2', sa.Numeric(14, 2), nullable=True))
    op.add_column('quotations', sa.Column('discount_pct', sa.Numeric(6, 3), nullable=True))
    op.add_column('quotations', sa.Column('discount_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('quotations', sa.Column('discount_request_note', sa.Text(), server_default='', nullable=False))


def downgrade() -> None:
    for col in ('discount_request_note', 'discount_requested_at', 'discount_pct', 'manager_price_per_m2',
                'auto_price_per_m2', 'pricing_mode'):
        op.drop_column('quotations', col)
    for col in ('customer_questions', 'first_contact', 'contact_method', 'governorate'):
        op.drop_column('customers', col)
