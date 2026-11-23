"""the cut sheets a work order had before its quotation was changed during manufacturing

One new empty column: nothing existing changes.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-23 12:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('work_orders', sa.Column('outputs_history', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('work_orders', 'outputs_history')
