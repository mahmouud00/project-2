"""picture of a model in each colour

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # new column with a default: existing models keep their main picture and get no colour pictures
    op.add_column('product_models', sa.Column('color_images', postgresql.JSONB(astext_type=sa.Text()),
                                              server_default='{}', nullable=False))


def downgrade() -> None:
    op.drop_column('product_models', 'color_images')
