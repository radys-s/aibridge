"""Runtime configuration with safe local-first storage defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from platformdirs import user_data_path

from aibridge.errors import ConfigurationError

DATA_DIR_ENV: Final = "AIBRIDGE_DATA_DIR"
SYNC_DIRECTORY_NAMES: Final = frozenset(
    {"onedrive", "dropbox", "icloud drive", "icloud", "google drive", "googledrive"}
)
PROJECT_MARKERS: Final = (".git", "pyproject.toml", "package.json", "Cargo.toml")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _validate_production_data_dir(data_dir: Path) -> None:
    """Reject locations where a mutable WAL database is unsafe or easy to commit."""
    if _is_within(data_dir, _repository_root()):
        raise ConfigurationError(f"{DATA_DIR_ENV} must not be inside the AI Bridge repository")
    current_dir = Path.cwd().resolve(strict=False)
    if any((current_dir / marker).exists() for marker in PROJECT_MARKERS) and _is_within(
        data_dir, current_dir
    ):
        raise ConfigurationError(f"{DATA_DIR_ENV} must not be inside the current project")
    for parent in (data_dir, *data_dir.parents):
        directory_name = parent.name.casefold()
        if directory_name in SYNC_DIRECTORY_NAMES or directory_name.startswith("onedrive - "):
            raise ConfigurationError(
                f"{DATA_DIR_ENV} must not be inside a synchronized cloud directory"
            )
        if (parent / ".git").exists():
            raise ConfigurationError(f"{DATA_DIR_ENV} must not be inside a Git repository")


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    busy_timeout_ms: int = 5_000

    @classmethod
    def load(cls) -> Settings:
        override = os.environ.get(DATA_DIR_ENV)
        if override:
            raw_input = Path(override)
            if not raw_input.is_absolute():
                raise ConfigurationError(f"{DATA_DIR_ENV} must be an absolute path")
            raw = raw_input.expanduser()
            data_dir = raw.resolve(strict=False)
            _validate_production_data_dir(data_dir)
        else:
            data_dir = user_data_path("AI Bridge", appauthor=False, ensure_exists=False).resolve(
                strict=False
            )
        return cls(data_dir=data_dir, database_path=data_dir / "aibridge.db")

    @classmethod
    def for_database(cls, database_path: Path) -> Settings:
        """Create isolated settings for tests/tools; callers must provide an absolute path."""
        if not database_path.is_absolute():
            raise ConfigurationError("Test database path must be absolute")
        resolved = database_path.resolve(strict=False)
        return cls(data_dir=resolved.parent, database_path=resolved)
