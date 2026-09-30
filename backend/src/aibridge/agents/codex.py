"""Codex CLI adapter using non-interactive execution (``codex exec``)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from aibridge.agents.claude import _build_prompt
from aibridge.domain.models import AgentHealth, AgentRunRequest, AgentRunResult
from aibridge.errors import AgentAdapterError


class CodexAdapter:
    """Invoke Codex with stdin input, JSONL events, and an output-schema artifact."""

    def __init__(self, executable: str = "codex", timeout_seconds: int = 120) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def doctor(self) -> AgentHealth:
        binary = shutil.which(self._executable)
        if not binary:
            return AgentHealth(
                available=False,
                provider="codex",
                detail=f"Binary '{self._executable}' not found on PATH",
            )
        try:
            result = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode == 0:
                return AgentHealth(
                    available=True,
                    provider="codex",
                    detail=f"Found {result.stdout.strip()} at {binary}",
                )
            return AgentHealth(
                available=False,
                provider="codex",
                detail=f"Version check returned exit code {result.returncode}",
            )
        except Exception as error:
            return AgentHealth(
                available=False, provider="codex", detail=f"Health probe failed: {error}"
            )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        binary = shutil.which(self._executable)
        if not binary:
            raise AgentAdapterError(f"Codex CLI '{self._executable}' is not installed")
        with tempfile.TemporaryDirectory(prefix="aibridge-codex-") as directory:
            output_path = Path(directory) / "structured-result.json"
            schema_path = Path(directory) / "agent-run-result.schema.json"
            try:
                schema_path.write_text(
                    resources.files("aibridge.schemas")
                    .joinpath("agent-run-result.schema.json")
                    .read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                cmd = self._command(binary, request, schema_path, output_path)
                result = subprocess.run(
                    cmd,
                    cwd=str(request.project_path),
                    input=_build_prompt(request),
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise AgentAdapterError(
                    f"Codex CLI timed out after {self._timeout_seconds}s"
                ) from error
            except OSError as error:
                raise AgentAdapterError(f"Failed to execute Codex CLI: {error}") from error
            if result.returncode != 0:
                raise AgentAdapterError(
                    f"Codex CLI failed with exit code {result.returncode}: {result.stderr.strip()}"
                )
            return self._parse_result(result.stdout, output_path, request.resume_vendor_session_id)

    @staticmethod
    def _command(
        binary: str, request: AgentRunRequest, schema_path: Path, output_path: Path
    ) -> list[str]:
        options = [
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if request.execution_policy.value == "read-only":
            options.extend(["--sandbox", "read-only"])
        if request.resume_vendor_session_id:
            return [binary, "exec", "resume", request.resume_vendor_session_id, *options, "-"]
        return [binary, "exec", "-C", str(request.project_path), *options, "-"]

    @staticmethod
    def _parse_result(
        stdout: str, output_path: Path, resumed_session_id: str | None
    ) -> AgentRunResult:
        vendor_session_id = resumed_session_id
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                vendor_session_id = str(event["thread_id"])
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise AgentAdapterError("Codex structured output is not a JSON object")
            payload["vendor_session_id"] = vendor_session_id
            return AgentRunResult.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as error:
            raise AgentAdapterError(f"Failed to parse Codex structured output: {error}") from error
