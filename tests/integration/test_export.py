"""Integration tests for MarkdownExporter."""

from __future__ import annotations

from pathlib import Path

from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.config import Settings
from aibridge.domain.models import MemoryKind, MemoryScope
from aibridge.memory.exporter import MarkdownExporter


def test_markdown_export(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    settings = Settings(database_path=db_path, data_dir=data_dir)
    repo = SQLiteMemoryRepository(settings)
    repo.initialize()

    proj_dir = tmp_path / "export_proj"
    proj_dir.mkdir()
    proj = repo.register_project(proj_dir)
    space_id, _ = repo.ensure_identity()

    repo.add_memory(
        space_id=space_id.id,
        project_id=proj.id,
        scope=MemoryScope.PROJECT,
        kind=MemoryKind.ARCHITECTURE,
        title="Event-Driven Microkernel",
        content="AI Bridge uses an append-only event log with SQLite projections.",
        subject_key="arch.microkernel",
        importance=90,
        volatility=10,
        confidence=1.0,
        pinned=True,
    )

    exporter = MarkdownExporter(repo)
    out_file = tmp_path / "export.md"
    result = exporter.export(proj_dir, out_file)

    assert result.is_file()
    content = result.read_text(encoding="utf-8")
    assert "# AI Bridge Memory Snapshot" in content
    assert "Event-Driven Microkernel" in content
    assert "arch.microkernel" in content
