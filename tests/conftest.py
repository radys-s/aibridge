from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from _pytest.config import Config

from aibridge.adapters.sqlite.repository import SQLiteMemoryRepository
from aibridge.config import Settings


def pytest_configure(config: Config) -> None:
    """Keep all test databases and scratch files in a unique OS-temp directory."""
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(tempfile.gettempdir()) / f"aibridge-pytest-{os.getpid()}")


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[SQLiteMemoryRepository]:
    repo = SQLiteMemoryRepository(Settings.for_database(tmp_path / "data" / "aibridge.db"))
    repo.initialize()
    yield repo


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    path = tmp_path / "example-project"
    path.mkdir()
    return path
