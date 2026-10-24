"""Golden tests: engine results vs reference values; any difference > 0.1 mm fails."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.compute import calculate

TOLERANCE_MM = Decimal("0.1")
FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))


def _cases():
    for path in FIXTURES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for i, case in enumerate(data["cases"]):
            yield pytest.param(data["snapshot"], case, id=f"{path.stem}-{i}")


@pytest.mark.parametrize("snapshot,case", list(_cases()))
def test_golden(snapshot, case):
    result = calculate(snapshot, opening_width_mm=case["opening_width_mm"],
                       opening_height_mm=case["opening_height_mm"], params=case.get("params"))
    for key, expected_cm in case.get("expected_cm", {}).items():
        got = result.values[key]
        assert abs(got - Decimal(str(expected_cm)) * 10) <= TOLERANCE_MM, f"{key}: {got} mm vs {expected_cm} cm"
    for key, expected_mm in case.get("expected_mm", {}).items():
        assert abs(result.values[key] - Decimal(str(expected_mm))) <= TOLERANCE_MM, key
