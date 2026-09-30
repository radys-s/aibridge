from __future__ import annotations

from pathlib import Path

import pytest

from aibridge.config import DATA_DIR_ENV, Settings
from aibridge.errors import ConfigurationError


def test_production_override_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, "relative/data")

    with pytest.raises(ConfigurationError, match="absolute"):
        Settings.load()


def test_production_override_rejects_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    repository_data = Path(__file__).resolve().parents[2] / "unsafe-data"
    monkeypatch.setenv(DATA_DIR_ENV, str(repository_data))

    with pytest.raises(ConfigurationError, match="repository"):
        Settings.load()


def test_production_override_rejects_sync_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sync_data = tmp_path.parent / "OneDrive" / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(sync_data))

    with pytest.raises(ConfigurationError, match="synchronized"):
        Settings.load()


def test_production_override_rejects_organization_onedrive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sync_data = tmp_path / "OneDrive - Example Org" / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(sync_data))

    with pytest.raises(ConfigurationError, match="synchronized"):
        Settings.load()


def test_production_override_rejects_git_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../.git/worktrees/example", encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(worktree / "data"))

    with pytest.raises(ConfigurationError, match="Git repository"):
        Settings.load()


def test_test_database_path_must_be_absolute() -> None:
    with pytest.raises(ConfigurationError, match="absolute"):
        Settings.for_database(Path("relative.db"))
