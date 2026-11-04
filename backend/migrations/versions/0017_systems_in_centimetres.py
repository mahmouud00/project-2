"""profile systems written in centimetres

The program works in centimetres. Systems made in millimetres (the Excel import made every system in mm) are
switched to cm when that keeps every number's meaning exactly: the system has no model and no published version
(formulas can hold plain numbers that cannot be converted safely), so the only numbers written in its unit are its
constants and the companies' calibration deltas / constant overrides. Those are divided by 10 (0.5 mm -> 0.05 cm:
the same length). A system with models or versions keeps millimetres; its author can review it. Lengths stored in
`*_mm` columns are millimetres whatever the system's unit, and are not touched.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-04 10:30:00
"""
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

# a value converts exactly when it has at most 5 decimals (the columns keep 6)
_EXACT = "{col} * 100000 = trunc({col} * 100000)"

SAFE = f"""
SELECT s.id FROM profile_systems s
WHERE s.unit = 'mm'
  AND NOT EXISTS (SELECT 1 FROM product_models m WHERE m.system_id = s.id)
  AND NOT EXISTS (SELECT 1 FROM formula_set_versions v WHERE v.system_id = s.id)
  AND NOT EXISTS (SELECT 1 FROM system_constants c WHERE c.system_id = s.id AND NOT ({_EXACT.format(col='c.value')}))
  AND NOT EXISTS (SELECT 1 FROM company_calibrations k WHERE k.system_id = s.id AND NOT ({_EXACT.format(col='k.delta')}))
  AND NOT EXISTS (SELECT 1 FROM company_constant_overrides o
                  WHERE o.system_id = s.id AND NOT ({_EXACT.format(col='o.value')}))
"""


def upgrade() -> None:
    op.execute(f"CREATE TEMP TABLE _systems_to_cm ON COMMIT DROP AS {SAFE}")
    op.execute("UPDATE system_constants SET value = value / 10, version = version + 1 "
               "WHERE system_id IN (SELECT id FROM _systems_to_cm)")
    op.execute("UPDATE company_calibrations SET delta = delta / 10, version = version + 1 "
               "WHERE system_id IN (SELECT id FROM _systems_to_cm)")
    op.execute("UPDATE company_constant_overrides SET value = value / 10, version = version + 1 "
               "WHERE system_id IN (SELECT id FROM _systems_to_cm)")
    op.execute("UPDATE profile_systems SET unit = 'cm', version = version + 1 WHERE id IN (SELECT id FROM _systems_to_cm)")
    op.execute("DROP TABLE _systems_to_cm")


def downgrade() -> None:
    # which systems were switched is not recorded; centimetre systems stay valid on the older code
    pass
