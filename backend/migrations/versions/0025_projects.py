"""projects: a customer's job in phases, each phase its own quotation and work order

A new table and three empty columns: every existing quotation and work order stays on its own (no project).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-18 12:00:00
"""
from alembic import op
import sqlalchemy as sa

from app.db import rls

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('projects',
    sa.Column('number', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_projects_company_id_companies')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_projects_customer_id_customers')),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name=op.f('fk_projects_branch_id_branches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    sa.UniqueConstraint('company_id', 'number', name=op.f('uq_projects_company_id_number')))
    for col in ('company_id', 'customer_id', 'branch_id'):
        op.create_index(op.f(f'ix_projects_{col}'), 'projects', [col], unique=False)
    rls.enable(op, "projects")

    for table in ('quotations', 'work_orders'):
        op.add_column(table, sa.Column('project_id', sa.UUID(), nullable=True))
        op.create_foreign_key(op.f(f'fk_{table}_project_id_projects'), table, 'projects', ['project_id'], ['id'])
        op.create_index(op.f(f'ix_{table}_project_id'), table, ['project_id'], unique=False)
    op.add_column('quotations', sa.Column('phase_name', sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column('quotations', 'phase_name')
    for table in ('quotations', 'work_orders'):
        op.drop_index(op.f(f'ix_{table}_project_id'), table_name=table)
        op.drop_constraint(op.f(f'fk_{table}_project_id_projects'), table, type_='foreignkey')
        op.drop_column(table, 'project_id')
    op.drop_table('projects')
