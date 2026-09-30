"""Deterministic secret detection used before any durable memory write."""

from __future__ import annotations

import re
from typing import Final

from aibridge.domain.models import SecretScanResult

SECRET_PATTERNS: Final = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
    ("api_secret_key", re.compile(r"\bsk_[a-zA-Z0-9_]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|secret|password|passwd)\b\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_./+\-=]{8,}"
        ),
    ),
)


class RegexSecretScanner:
    """Conservative local scanner that never returns matched secret material."""

    def scan(self, text: str) -> SecretScanResult:
        findings = tuple(code for code, pattern in SECRET_PATTERNS if pattern.search(text))
        return SecretScanResult(safe=not findings, finding_codes=findings)
