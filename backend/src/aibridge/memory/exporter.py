"""One-way Markdown snapshot export for project memory items."""

from __future__ import annotations

from pathlib import Path

from aibridge.domain.models import MemoryItem, MemoryKind, MemoryStatus
from aibridge.errors import ProjectNotRegisteredError
from aibridge.ports.interfaces import MemoryRepository


class MarkdownExporter:
    """Exports active project memory items into a formatted Markdown snapshot."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def export(self, project_path: Path, output_path: Path) -> Path:
        project = self._repository.find_project_by_path(project_path)
        if project is None:
            raise ProjectNotRegisteredError(
                f"Project is not registered: {project_path}. "
                "Run 'aibridge project register <path>'."
            )

        memories: list[MemoryItem] = []
        cursor: str | None = None
        while True:
            page = self._repository.list_memories(
                project_id=project.id, status=MemoryStatus.ACTIVE, limit=100, cursor=cursor
            )
            memories.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        revision_token = self._repository.memory_revision_token(project.id)

        lines: list[str] = [
            f"# AI Bridge Memory Snapshot — {project.name}",
            "",
            f"- **Project ID**: `{project.id}`",
            f"- **Revision Token**: `{revision_token}`",
            f"- **Active Memory Items**: {len(memories)}",
            "",
            "---",
            "",
        ]

        grouped: dict[MemoryKind, list[MemoryItem]] = {kind: [] for kind in MemoryKind}
        for item in memories:
            grouped[item.kind].append(item)

        for kind in MemoryKind:
            items = grouped[kind]
            if not items:
                continue
            lines.append(f"## {kind.value.capitalize()}")
            lines.append("")
            for item in items:
                lines.append(f"### {item.title}")
                if item.subject_key:
                    lines.append(f"- **Subject**: `{item.subject_key}`")
                lines.append(
                    f"- **Importance**: {item.importance}% | "
                    f"**Confidence**: {int(item.confidence * 100)}%"
                )
                lines.append("")
                lines.append(item.content)
                lines.append("")
                if item.provenance:
                    lines.append("**Provenance**:")
                    for prov in item.provenance:
                        lines.append(
                            f"  - Source: `{prov.source_type}` "
                            f"({prov.source_agent or 'system'}) at {prov.created_at.isoformat()}"
                        )
                lines.append("")

        out_file = output_path.resolve(strict=False)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("\n".join(lines), encoding="utf-8")
        return out_file
