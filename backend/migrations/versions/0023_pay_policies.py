"""pay policies, work zones, public holidays, attendance decisions; payslips from the attendance

New tables only, and new columns with defaults: every employee keeps no policy (paid as before, from the salary,
entries and unpaid leave), every old payslip keeps its numbers (the new ones are 0), every punch came from a device.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12 19:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db import rls

revision = '0023'
down_revision = '0022'
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


def _index(table: str, *cols: str) -> None:
    for c in cols:
        op.create_index(op.f(f'ix_{table}_{c}'), table, [c], unique=False)


def upgrade() -> None:
    op.create_table('pay_policies',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    *_entity('pay_policies'),
    sa.UniqueConstraint('company_id', 'code', name=op.f('uq_pay_policies_company_id_code')))
    _index('pay_policies', 'company_id')
    rls.enable(op, "pay_policies")

    op.create_table('work_zones',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('latitude', sa.Numeric(9, 6), nullable=False),
    sa.Column('longitude', sa.Numeric(9, 6), nullable=False),
    sa.Column('radius_km', sa.Numeric(8, 2), nullable=False),
    sa.Column('transport_allowance', sa.Numeric(14, 2), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    *_entity('work_zones'))
    _index('work_zones', 'company_id')
    rls.enable(op, "work_zones")

    op.create_table('public_holidays',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    *_entity('public_holidays'),
    sa.UniqueConstraint('company_id', 'day', name=op.f('uq_public_holidays_company_id_day')))
    _index('public_holidays', 'company_id')
    rls.enable(op, "public_holidays")

    op.create_table('attendance_days',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=True),
    sa.Column('excuse', sa.String(length=20), nullable=False),
    sa.Column('permission_minutes', sa.Integer(), nullable=False),
    sa.Column('manual_in', sa.Time(), nullable=True),
    sa.Column('manual_out', sa.Time(), nullable=True),
    sa.Column('start_source', sa.String(length=10), nullable=True),
    sa.Column('conflict_notified', sa.Boolean(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    *_entity('attendance_days'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_attendance_days_employee_id_employees')),
    sa.UniqueConstraint('company_id', 'employee_id', 'day', name=op.f('uq_attendance_days_company_id_employee_id_day')))
    _index('attendance_days', 'company_id', 'employee_id', 'day')
    rls.enable(op, "attendance_days")

    op.add_column('employees', sa.Column('pay_policy_id', sa.UUID(), nullable=True))
    op.add_column('employees', sa.Column('manager_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_employees_pay_policy_id_pay_policies'), 'employees', 'pay_policies',
                          ['pay_policy_id'], ['id'])
    op.create_foreign_key(op.f('fk_employees_manager_id_employees'), 'employees', 'employees', ['manager_id'], ['id'])
    _index('employees', 'pay_policy_id')

    op.add_column('employee_entries', sa.Column('quantity', sa.Numeric(12, 2), nullable=True))
    op.add_column('employee_entries', sa.Column('rate', sa.Numeric(14, 2), nullable=True))

    op.add_column('attendance_punches', sa.Column('source', sa.String(length=10), nullable=False, server_default='device'))
    op.add_column('attendance_punches', sa.Column('latitude', sa.Numeric(9, 6), nullable=True))
    op.add_column('attendance_punches', sa.Column('longitude', sa.Numeric(9, 6), nullable=True))

    for col, typ in (("present_days", sa.Numeric(6, 2)), ("absent_days", sa.Numeric(6, 2)),
                     ("late_minutes", sa.Integer()), ("attendance_deduction", sa.Numeric(14, 2)),
                     ("overtime_minutes", sa.Integer()), ("overtime_amount", sa.Numeric(14, 2)),
                     ("allowances", sa.Numeric(14, 2)), ("piecework", sa.Numeric(14, 2)),
                     ("collections", sa.Numeric(14, 2)), ("commission", sa.Numeric(14, 2)),
                     ("review_days", sa.Integer())):
        op.add_column('payslips', sa.Column(col, typ, nullable=False, server_default='0'))
    op.add_column('payslips', sa.Column('commission_forced', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('payslips', sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                                        server_default='{}'))


def downgrade() -> None:
    for col in ("present_days", "absent_days", "late_minutes", "attendance_deduction", "overtime_minutes",
                "overtime_amount", "allowances", "piecework", "collections", "commission", "review_days",
                "commission_forced", "details"):
        op.drop_column('payslips', col)
    for col in ("source", "latitude", "longitude"):
        op.drop_column('attendance_punches', col)
    op.drop_column('employee_entries', 'quantity')
    op.drop_column('employee_entries', 'rate')
    op.drop_constraint(op.f('fk_employees_manager_id_employees'), 'employees', type_='foreignkey')
    op.drop_constraint(op.f('fk_employees_pay_policy_id_pay_policies'), 'employees', type_='foreignkey')
    op.drop_index(op.f('ix_employees_pay_policy_id'), table_name='employees')
    op.drop_column('employees', 'manager_id')
    op.drop_column('employees', 'pay_policy_id')
    for t in ("attendance_days", "public_holidays", "work_zones", "pay_policies"):
        op.drop_table(t)
