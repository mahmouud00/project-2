"""the installation order permission

`field.install_doc` lets a user see and download a work order's installation order (every window with where it
goes). The built-in administrator, installations manager and technician roles get it; other roles are as they were.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-10 20:00:00
"""
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE roles SET permissions = array_append(permissions, 'field.install_doc') "
               "WHERE is_builtin AND code IN ('admin', 'field_manager', 'technician') "
               "AND NOT ('field.install_doc' = ANY(permissions))")


def downgrade() -> None:
    op.execute("UPDATE roles SET permissions = array_remove(permissions, 'field.install_doc')")
