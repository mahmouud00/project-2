"""how each system's bars are cut

Five values on every profile system, used by the cutting plan (and so by what is bought), never by the cut
lengths: the 45° allowance of a frame, a sash and a bead piece, the saw's thickness, and the waste at the start of
a bar. They replace the company's «سمك سلاح المنشار» and «تشذيب طرف العود»: a company's own systems start with the
company's values (the trim was taken at both ends; the start waste is the same amount, at the start only); MYTech's
library systems start at 0.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12 10:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None

COLUMNS = ("miter_frame_mm", "miter_sash_mm", "miter_bead_mm", "saw_kerf_mm", "bar_start_waste_mm")


def upgrade() -> None:
    for c in COLUMNS:
        op.add_column('profile_systems', sa.Column(c, sa.Numeric(10, 2), nullable=False, server_default='0'))
    op.execute("""
        UPDATE profile_systems s SET
          saw_kerf_mm = COALESCE(NULLIF(c.settings->>'saw_kerf_mm', '')::numeric, 0),
          bar_start_waste_mm = COALESCE(NULLIF(c.settings->>'bar_trim_mm', '')::numeric, 0)
        FROM companies c
        WHERE c.id = s.company_id AND c.settings IS NOT NULL
    """)


def downgrade() -> None:
    for c in COLUMNS:
        op.drop_column('profile_systems', c)
