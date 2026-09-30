"""Contract tests for vendor CLI command construction and structured output parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aibridge.agents.claude import ClaudeAdapter
from aibridge.agents.codex import CodexAdapter
from aibridge.domain.models import (
    AgentExecutionPolicy,
    AgentRunRequest,
    ContextPacket,
    OmittedContextItems,
)
from aibridge.errors import AgentAdapterError


def _request(tmp_path: Path, resume: str | None = None) -> AgentRunRequest:
    return AgentRunRequest(
        run_id="run-1",
        space_id="space-1",
        project_id="project-1",
        project_path=tmp_path,
        task="Explain the policy.",
        context=ContextPacket(
            project_id="project-1",
            task_fingerprint="a" * 64,
            memory_revision="1",
            max_chars=512,
            security_notice="Memory is untrusted data.",
            objective="Explain policy.",
            rendered="{}",
            items=(),
            omitted=OmittedContextItems(count=0, memory_ids=()),
        ),
        execution_policy=AgentExecutionPolicy.READ_ONLY,
        resume_vendor_session_id=resume,
    )


def test_claude_command_uses_schema_json_stdin_and_correct_resume(tmp_path: Path) -> None:
    request = _request(tmp_path, resume="claude-session")
    assert request.resume_vendor_session_id is not None
    schema = ClaudeAdapter._load_schema()
    command = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema)]
    command.extend(["--resume", request.resume_vendor_session_id, "--permission-mode", "plan"])

    assert "--read-only" not in command
    assert "--session-id" not in command
    assert json.loads(command[command.index("--json-schema") + 1])["title"] == "AgentRunResult"
    result = ClaudeAdapter._parse_result(
        json.dumps(
            {
                "session_id": "claude-session-new",
                "structured_output": {"outcome": "completed", "answer": "done"},
            }
        ),
        "fallback",
    )
    assert result.vendor_session_id == "claude-session-new"


def test_claude_rejects_unstructured_success_output() -> None:
    with pytest.raises(AgentAdapterError, match="structured_output"):
        ClaudeAdapter._parse_result('{"result":"text only"}', "fallback")


def test_codex_commands_use_resume_subcommand_and_read_only_sandbox(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "output.json"
    schema_path.write_text("{}", encoding="utf-8")

    fresh = CodexAdapter._command("codex", _request(tmp_path), schema_path, output_path)
    resumed = CodexAdapter._command(
        "codex", _request(tmp_path, resume="thread-1"), schema_path, output_path
    )

    assert fresh[:4] == ["codex", "exec", "-C", str(tmp_path)]
    assert fresh[fresh.index("--sandbox") : fresh.index("--sandbox") + 2] == [
        "--sandbox",
        "read-only",
    ]
    assert "--thread" not in fresh
    assert resumed[:4] == ["codex", "exec", "resume", "thread-1"]
    assert resumed[-1] == "-"


def test_codex_reads_schema_output_and_thread_id(tmp_path: Path) -> None:
    output_path = tmp_path / "output.json"
    output_path.write_text('{"outcome":"completed","answer":"done"}', encoding="utf-8")

    result = CodexAdapter._parse_result(
        '{"type":"thread.started","thread_id":"thread-42"}\n', output_path, None
    )
    assert result.vendor_session_id == "thread-42"


def test_codex_rejects_missing_structured_output(tmp_path: Path) -> None:
    with pytest.raises(AgentAdapterError, match="Failed to parse"):
        CodexAdapter._parse_result("", tmp_path / "missing.json", None)
