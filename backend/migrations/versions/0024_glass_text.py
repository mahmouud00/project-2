"""the glass as written (e.g. «عاكس بني - سنجل») on quotation lines and work order items

Two new empty columns: nothing existing changes. A quotation made from a survey takes the survey's glass colour and
layers; the glass order groups the glass by its type, or by this text when no glass type was chosen.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-14 18:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('quotation_lines', sa.Column('glass_text', sa.String(length=120), nullable=True))
    op.add_column('work_order_items', sa.Column('glass_text', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('work_order_items', 'glass_text')
    op.drop_column('quotation_lines', 'glass_text')
