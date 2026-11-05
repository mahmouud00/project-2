"""links customers open without an account (quotation approval, invoice view)

A new table only: nothing existing changes. Only the SHA-256 of each link's token is stored.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05 02:00:00
"""
from alembic import op
import sqlalchemy as sa

from app.db import rls

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('document_shares',
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('doc_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('views', sa.Integer(), nullable=False),
    sa.Column('response', sa.String(length=20), nullable=True),
    sa.Column('response_note', sa.Text(), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_document_shares_company_id_companies')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_shares')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_document_shares_token_hash'))
    )
    op.create_index(op.f('ix_document_shares_company_id'), 'document_shares', ['company_id'], unique=False)
    op.create_index(op.f('ix_document_shares_doc_id'), 'document_shares', ['doc_id'], unique=False)
    rls.enable(op, "document_shares")


def downgrade() -> None:
    op.drop_index(op.f('ix_document_shares_doc_id'), table_name='document_shares')
    op.drop_index(op.f('ix_document_shares_company_id'), table_name='document_shares')
    op.drop_table('document_shares')
