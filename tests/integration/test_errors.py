"""Expected failures end in a stable error code, never a traceback or a bare 500."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aibridge.api.app import create_api_app
from aibridge.cli import main
from aibridge.config import DATA_DIR_ENV, Settings
from aibridge.domain.models import MemoryCandidateProposal, MemoryKind


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(path))
    return path


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["candidate", "approve", "missing-id"], "candidate_not_found"),
        (["candidate", "reject", "missing-id", "--reason", "wrong"], "candidate_not_found"),
        (["run-show", "missing-id"], "run_not_found"),
    ],
)
def test_cli_unknown_ids_print_stable_code(
    data_dir: Path, capsys: pytest.CaptureFixture[str], argv: list[str], code: str
) -> None:
    assert main(argv) == 2
    assert capsys.readouterr().err.startswith(f"error[{code}]: ")


def test_cli_export_of_unregistered_project_prints_stable_code(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["export", "--project", str(tmp_path), "--output", str(tmp_path / "out.md")]

    assert main(argv) == 2
    assert capsys.readouterr().err.startswith("error[project_not_registered]: ")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_api_app(Settings.for_database(tmp_path / "data" / "aibridge.db")))


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "code"),
    [
        ("PATCH", "/v1/candidates/missing-id/approve", None, 404, "candidate_not_found"),
        ("PATCH", "/v1/candidates/missing-id/reject", {"reason": "x"}, 404, "candidate_not_found"),
        ("GET", "/v1/memory/missing-id", None, 404, "memory_not_found"),
        ("GET", "/v1/runs/missing-id", None, 404, "run_not_found"),
        ("GET", "/v1/projects/missing-id", None, 404, "project_not_registered"),
        ("GET", "/v1/memory?project_path=/not/registered", None, 404, "project_not_registered"),
        ("GET", "/v1/runs?project_path=/not/registered", None, 404, "project_not_registered"),
        ("GET", "/v1/candidates?project_path=/x", None, 404, "project_not_registered"),
    ],
)
def test_api_errors_carry_stable_code(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, str] | None,
    status: int,
    code: str,
) -> None:
    with client:
        response = client.request(method, path, json=body)

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["detail"]


def test_api_rejected_input_is_a_client_error_with_code(client: TestClient, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with client:
        client.post("/v1/projects", json={"path": str(project)})
        response = client.post(
            "/v1/memory",
            json={
                "project_path": str(project),
                "kind": "learning",
                "title": "Login",
                "content": "password = hunter2hunter2",
            },
        )

    assert response.status_code == 400
    assert response.json()["code"] == "secret_detected"


def test_api_approving_twice_reports_candidate_not_pending(
    client: TestClient, tmp_path: Path
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    with client:
        application = client.app.state.application  # type: ignore[attr-defined]
        project = application.projects.register(project_path)
        candidate = application.repository.save_candidate(
            space_id=project.space_id,
            project_id=project.id,
            proposal=MemoryCandidateProposal(kind=MemoryKind.DECISION, title="T", content="C"),
        )
        first = client.patch(f"/v1/candidates/{candidate.id}/approve")
        second = client.patch(f"/v1/candidates/{candidate.id}/approve")

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["code"] == "candidate_not_pending"
