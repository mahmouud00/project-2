"""Logging that never writes personal data, tokens or passwords.

Rule: log ids, never names/phones/addresses. This filter is a safety net that
masks anything that looks like a secret or an Egyptian phone / national id.
"""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    # bearer tokens first, so the key/value rule below cannot leave the token behind
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_\.=]+"), "Bearer ***"),
    (re.compile(r"(?i)(authorization|password|passwd|token|secret|refresh_token|access_token)(\"?\s*[:=]\s*\"?)(?!Bearer \*\*\*)([^\s\",]+)"), r"\1\2***"),
    (re.compile(r"\b[23]\d{13}\b"), "[NATIONAL_ID]"),           # Egyptian national id (14 digits)
    (re.compile(r"(?<!\d)(\+?20)?0?1[0125]\d{8}(?!\d)"), "[PHONE]"),  # Egyptian mobile
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactingFilter())
