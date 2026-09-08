"""Centralized best-effort redaction for all captured user-visible data."""

from __future__ import annotations

import re
from typing import Mapping

REDACTED = "********"
AUTHORIZATION = re.compile(r"(Authorization\s*[:=]\s*(?:Bearer\s+)?)\S+", re.I)


class SecretRedactor:
    def __init__(self, values: Mapping[str, str | None] | None = None) -> None:
        values = values or {}
        secret_names = ("TOKEN", "API_KEY", "PASSWORD", "CLIENT_SECRET")
        self.secrets = sorted({str(values[name]) for name in secret_names if values.get(name)}, key=len, reverse=True)

    def redact(self, value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value)
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        return AUTHORIZATION.sub(r"\1" + REDACTED, text)
