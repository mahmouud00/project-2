"""fingerprint devices and their punches (الحضور والانصراف)

Two new tables, and one new empty column on employees (their number on the fingerprint device). Nothing existing
changes.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12 17:00:00
"""
from alembic import op
import sqlalchemy as sa

from app.db import rls

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def _entity(table: str) -> list:
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f(f'fk_{table}_company_id_companies')),
        sa.PrimaryKeyConstraint('id', name=op.f(f'pk_{table}')),
    ]


def upgrade() -> None:
    op.add_column('employees', sa.Column('attendance_pin', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_employees_attendance_pin'), 'employees', ['attendance_pin'], unique=False)

    op.create_table('attendance_devices',
    sa.Column('serial', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_punch_at', sa.DateTime(timezone=False), nullable=True),
    sa.Column('attlog_stamp', sa.String(length=40), nullable=True),
    sa.Column('info', sa.String(length=200), nullable=False),
    *_entity('attendance_devices'),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], name=op.f('fk_attendance_devices_branch_id_branches')),
    sa.UniqueConstraint('serial', name=op.f('uq_attendance_devices_serial'))
    )
    op.create_index(op.f('ix_attendance_devices_company_id'), 'attendance_devices', ['company_id'], unique=False)
    rls.enable(op, "attendance_devices")

    op.create_table('attendance_punches',
    sa.Column('device_serial', sa.String(length=40), nullable=False),
    sa.Column('pin', sa.String(length=20), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=True),
    sa.Column('punched_at', sa.DateTime(timezone=False), nullable=False),
    sa.Column('state', sa.Integer(), nullable=False),
    sa.Column('verify', sa.Integer(), nullable=False),
    *_entity('attendance_punches'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_attendance_punches_employee_id_employees')),
    sa.UniqueConstraint('company_id', 'device_serial', 'pin', 'punched_at',
                        name=op.f('uq_attendance_punches_company_id_device_serial_pin_punched_at')),
    )
    for col in ('company_id', 'pin', 'employee_id', 'punched_at'):
        op.create_index(op.f(f'ix_attendance_punches_{col}'), 'attendance_punches', [col], unique=False)
    rls.enable(op, "attendance_punches")


def downgrade() -> None:
    op.drop_table('attendance_punches')
    op.drop_table('attendance_devices')
    op.drop_index(op.f('ix_employees_attendance_pin'), table_name='employees')
    op.drop_column('employees', 'attendance_pin')
