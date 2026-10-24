"""Semantic version comparison for server/client compatibility."""
from __future__ import annotations

import re


def parse(version: str) -> tuple[int, int, int]:
    m = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", version or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def is_compatible(client: str, minimum: str) -> bool:
    return parse(client) >= parse(minimum)
