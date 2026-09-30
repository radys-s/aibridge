"""Small contract checks for the safe Phase A local API surface."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aibridge.api.app import create_api_app
from aibridge.config import Settings


def test_health_and_empty_projects_are_available(tmp_path: Path) -> None:
    app = create_api_app(Settings.for_database(tmp_path / "data" / "aibridge.db"))
    with TestClient(app) as client:
        health = client.get("/v1/health")
        projects = client.get("/v1/projects")

    assert health.status_code == 200
    assert health.json()["schema_version"] == 2
    assert projects.status_code == 200
    assert projects.json() == []


def test_run_submission_is_honestly_unavailable(tmp_path: Path) -> None:
    app = create_api_app(Settings.for_database(tmp_path / "data" / "aibridge.db"))
    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={"project_path": str(tmp_path), "agent": "codex", "task": "Do not run"},
        )

    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "phase_not_ready"
