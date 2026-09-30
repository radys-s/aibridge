"""Evidence verification for proposed memory candidates."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from aibridge.domain.models import Evidence, EvidenceType


class EvidenceVerifier:
    """Verifies evidence paths, quotes, and bounds against real project files and tasks."""

    def verify(
        self,
        evidence_items: Sequence[Evidence],
        project_path: Path,
        task_prompt: str,
    ) -> tuple[bool, tuple[str, ...]]:
        if not evidence_items:
            return True, ()

        risk_codes: list[str] = []
        project_root = project_path.resolve(strict=False)

        for entry in evidence_items:
            if entry.type == EvidenceType.FILE:
                if not entry.path:
                    risk_codes.append("file_evidence_missing_path")
                    continue
                try:
                    relative = Path(entry.path)
                    target = (project_root / relative).resolve(strict=False)
                    if not target.is_relative_to(project_root):
                        risk_codes.append("file_evidence_path_traversal")
                        continue
                    if not target.is_file():
                        risk_codes.append("file_evidence_not_found")
                        continue
                    content = target.read_text(encoding="utf-8", errors="replace")
                    lines = content.splitlines()
                    has_line_range = entry.line_start is not None or entry.line_end is not None
                    if has_line_range:
                        if (
                            entry.line_start is None
                            or entry.line_end is None
                            or entry.line_start < 1
                            or entry.line_end < entry.line_start
                            or entry.line_end > len(lines)
                        ):
                            risk_codes.append("file_evidence_invalid_line_range")
                            continue
                        quote_scope = "\n".join(lines[entry.line_start - 1 : entry.line_end])
                    else:
                        quote_scope = content
                    if entry.quote and entry.quote not in quote_scope:
                        risk_codes.append(
                            "file_evidence_quote_outside_line_range"
                            if has_line_range
                            else "file_evidence_quote_mismatch"
                        )
                except Exception:
                    risk_codes.append("file_evidence_read_error")

            elif entry.type == EvidenceType.USER:
                if entry.quote and entry.quote not in task_prompt:
                    risk_codes.append("user_evidence_quote_mismatch")

        is_valid = len(risk_codes) == 0
        return is_valid, tuple(risk_codes)
