"""Rejected memory input names the field and the limit it broke."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibridge.api.app import create_api_app
from aibridge.cli import main
from aibridge.config import DATA_DIR_ENV, Settings


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--title", "x" * 301], "title: String should have at most 300 characters"),
        (["--title", "   "], "title: String should have at least 1 character"),
        (["--importance", "500"], "importance: Input should be less than or equal to 100"),
        (["--confidence", "1.5"], "confidence: Input should be less than or equal to 1"),
    ],
)
def test_memory_add_names_the_invalid_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    expected: str,
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    project = tmp_path / "project"
    project.mkdir()
    assert main(["project", "register", str(project)]) == 0
    capsys.readouterr()
    argv = ["memory", "add", "--project", str(project), "--kind", "learning"]
    defaults = {"--title": "Title", "--content": "Content"}
    for flag, value in defaults.items():
        if flag not in flags:
            argv += [flag, value]

    assert main([*argv, *flags]) == 2
    error = capsys.readouterr().err
    assert error.startswith("error[invalid_input]: ")
    assert expected in error


def test_api_rejects_overlong_title_with_field_location(tmp_path: Path) -> None:
    app = create_api_app(Settings.for_database(tmp_path / "data" / "aibridge.db"))
    body = {"project_path": str(tmp_path), "kind": "learning", "title": "x" * 301, "content": "c"}
    with TestClient(app) as client:
        response = client.post("/v1/memory", json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "title"]
