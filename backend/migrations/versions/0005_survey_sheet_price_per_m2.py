"""survey sheet columns, price per m² on quotation lines

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # only new nullable / defaulted columns: existing rows keep every value (no RLS change: same tables)
    op.add_column('site_surveys', sa.Column('kind', sa.String(length=20), server_default='window', nullable=False))
    op.add_column('site_surveys', sa.Column('floor', sa.String(length=40), nullable=True))
    op.add_column('site_surveys', sa.Column('technician', sa.String(length=120), nullable=True))
    for name, type_ in (('total_height_mm', sa.Numeric(precision=12, scale=2)), ('unit_kind', sa.String(length=20)),
                        ('color_text', sa.String(length=80)), ('glass_layers', sa.String(length=10)),
                        ('glass_color', sa.String(length=80)), ('screen_type', sa.String(length=20)),
                        ('installation_method', sa.String(length=120)), ('motor_type', sa.String(length=120))):
        op.add_column('survey_openings', sa.Column(name, type_, nullable=True))
    op.add_column('survey_openings', sa.Column('application', sa.Text(), server_default='', nullable=False))
    op.add_column('quotation_lines', sa.Column('price_per_m2', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('quotation_lines', sa.Column('billed_area_m2', sa.Numeric(precision=12, scale=4), nullable=True))
    # existing lines were priced without a minimum area: their billed area is their area
    op.execute("UPDATE quotation_lines SET billed_area_m2 = area_m2")
    op.alter_column('quotation_lines', 'billed_area_m2', nullable=False, server_default='0')


def downgrade() -> None:
    op.drop_column('quotation_lines', 'billed_area_m2')
    op.drop_column('quotation_lines', 'price_per_m2')
    for name in ('application', 'motor_type', 'installation_method', 'screen_type', 'glass_color', 'glass_layers',
                 'color_text', 'unit_kind', 'total_height_mm'):
        op.drop_column('survey_openings', name)
    op.drop_column('site_surveys', 'technician')
    op.drop_column('site_surveys', 'floor')
    op.drop_column('site_surveys', 'kind')
