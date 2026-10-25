"""arch (أرج) above a unit: arch model on survey openings and quotation lines, arch lines linked to their unit

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # new nullable columns only: existing rows are unchanged
    op.add_column('survey_openings', sa.Column('top_model_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_survey_openings_top_model_id_product_models'), 'survey_openings',
                          'product_models', ['top_model_id'], ['id'])
    op.add_column('quotation_lines', sa.Column('top_model_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_quotation_lines_top_model_id_product_models'), 'quotation_lines',
                          'product_models', ['top_model_id'], ['id'])
    op.add_column('quotation_lines', sa.Column('parent_line_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_quotation_lines_parent_line_id_quotation_lines'), 'quotation_lines',
                          'quotation_lines', ['parent_line_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_quotation_lines_parent_line_id'), 'quotation_lines', ['parent_line_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quotation_lines_parent_line_id'), table_name='quotation_lines')
    op.drop_constraint(op.f('fk_quotation_lines_parent_line_id_quotation_lines'), 'quotation_lines', type_='foreignkey')
    op.drop_column('quotation_lines', 'parent_line_id')
    op.drop_constraint(op.f('fk_quotation_lines_top_model_id_product_models'), 'quotation_lines', type_='foreignkey')
    op.drop_column('quotation_lines', 'top_model_id')
    op.drop_constraint(op.f('fk_survey_openings_top_model_id_product_models'), 'survey_openings', type_='foreignkey')
    op.drop_column('survey_openings', 'top_model_id')
