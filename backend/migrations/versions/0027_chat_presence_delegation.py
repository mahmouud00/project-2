"""chat between users, last seen, delegating permissions, the customer's WhatsApp number

New tables, and new empty columns (users.last_seen_at, customers.whatsapp): nothing existing changes.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-24 13:00:00
"""
from alembic import op
import sqlalchemy as sa

from app.db import rls

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def _ids(table: str, entity: bool) -> list:
    cols = [sa.Column('id', sa.UUID(), nullable=False), sa.Column('company_id', sa.UUID(), nullable=False)]
    if entity:
        cols += [sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
                 sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
                 sa.Column('created_by', sa.UUID(), nullable=True), sa.Column('updated_by', sa.UUID(), nullable=True),
                 sa.Column('version', sa.Integer(), nullable=False)]
    return cols + [sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f(f'fk_{table}_company_id_companies')),
                   sa.PrimaryKeyConstraint('id', name=op.f(f'pk_{table}'))]


def upgrade() -> None:
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('customers', sa.Column('whatsapp', sa.String(length=40), nullable=True))

    op.create_table('chat_conversations',
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('direct_key', sa.String(length=80), nullable=True),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    *_ids('chat_conversations', True),
    sa.UniqueConstraint('company_id', 'direct_key', name=op.f('uq_chat_conversations_company_id_direct_key')))
    op.create_index(op.f('ix_chat_conversations_company_id'), 'chat_conversations', ['company_id'])
    op.create_index(op.f('ix_chat_conversations_last_message_at'), 'chat_conversations', ['last_message_at'])
    rls.enable(op, "chat_conversations")

    op.create_table('chat_members',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    *_ids('chat_members', False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], ondelete='CASCADE',
                            name=op.f('fk_chat_members_conversation_id_chat_conversations')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_chat_members_user_id_users')),
    sa.UniqueConstraint('conversation_id', 'user_id', name=op.f('uq_chat_members_conversation_id_user_id')))
    for c in ('company_id', 'conversation_id', 'user_id'):
        op.create_index(op.f(f'ix_chat_members_{c}'), 'chat_members', [c])
    rls.enable(op, "chat_members")

    op.create_table('chat_messages',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('sender_id', sa.UUID(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('file_sha', sa.String(length=64), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_mime', sa.String(length=100), nullable=True),
    sa.Column('file_size', sa.BigInteger(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    *_ids('chat_messages', False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], ondelete='CASCADE',
                            name=op.f('fk_chat_messages_conversation_id_chat_conversations')),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_chat_messages_sender_id_users')))
    op.create_index(op.f('ix_chat_messages_company_id'), 'chat_messages', ['company_id'])
    op.create_index('ix_chat_messages_conversation_at', 'chat_messages', ['conversation_id', 'at'])
    rls.enable(op, "chat_messages")

    op.create_table('permission_delegations',
    sa.Column('from_user_id', sa.UUID(), nullable=False),
    sa.Column('to_user_id', sa.UUID(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    *_ids('permission_delegations', True),
    sa.ForeignKeyConstraint(['from_user_id'], ['users.id'], name=op.f('fk_permission_delegations_from_user_id_users')),
    sa.ForeignKeyConstraint(['to_user_id'], ['users.id'], name=op.f('fk_permission_delegations_to_user_id_users')))
    for c in ('company_id', 'from_user_id', 'to_user_id', 'ends_at'):
        op.create_index(op.f(f'ix_permission_delegations_{c}'), 'permission_delegations', [c])
    rls.enable(op, "permission_delegations")


def downgrade() -> None:
    for t in ('permission_delegations', 'chat_messages', 'chat_members', 'chat_conversations'):
        op.drop_table(t)
    op.drop_column('customers', 'whatsapp')
    op.drop_column('users', 'last_seen_at')
