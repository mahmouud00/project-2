"""total height on quotation lines (area for the price = width × total height when given)

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # new nullable column: existing lines keep their area and price
    op.add_column('quotation_lines', sa.Column('total_height_mm', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('quotation_lines', 'total_height_mm')
