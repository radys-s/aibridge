"""Command-line interface for AI Bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from aibridge.bootstrap import create_application
from aibridge.domain.models import (
    AgentExecutionPolicy,
    CandidateReviewState,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
)
from aibridge.errors import AIBridgeError


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _print_json(value: Any) -> None:
    print(json.dumps(value, default=_json_default, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aibridge", description="AI Bridge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check storage and agent capabilities")
    doctor.add_argument("--live", action="store_true", help="Perform live CLI agent health checks")
    doctor.set_defaults(handler=_doctor)

    project = subparsers.add_parser("project", help="Manage projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    register = project_sub.add_parser("register", help="Register a local project mount")
    register.add_argument("path", type=Path)
    register.add_argument("--name")
    register.set_defaults(handler=_project_register)

    memory = subparsers.add_parser("memory", help="Manage durable memory")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    add = memory_sub.add_parser("add", help="Add a manually verified memory item")
    add.add_argument("--project", type=Path, required=True)
    add.add_argument("--kind", choices=[value.value for value in MemoryKind], required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--content", required=True)
    add.add_argument("--scope", choices=[value.value for value in MemoryScope], default="project")
    add.add_argument("--subject")
    add.add_argument("--importance", type=int, default=50)
    add.add_argument("--volatility", type=int, default=50)
    add.add_argument("--confidence", type=float, default=1.0)
    add.add_argument("--pinned", action="store_true")
    add.set_defaults(handler=_memory_add)

    list_command = memory_sub.add_parser("list", help="List project and global memory")
    list_command.add_argument("--project", type=Path, required=True)
    list_command.add_argument("--status", choices=[value.value for value in MemoryStatus])
    list_command.add_argument("--limit", type=int, default=25)
    list_command.add_argument("--cursor")
    list_command.set_defaults(handler=_memory_list)

    show = memory_sub.add_parser("show", help="Show one memory item")
    show.add_argument("memory_id")
    show.set_defaults(handler=_memory_show)

    candidate = subparsers.add_parser("candidate", help="Manage proposed memory candidates")
    candidate_sub = candidate.add_subparsers(dest="candidate_command", required=True)
    cand_list = candidate_sub.add_parser("list", help="List proposed candidates")
    cand_list.add_argument("--project", type=Path, required=True)
    cand_list.add_argument(
        "--status", choices=[value.value for value in CandidateReviewState], default="pending"
    )
    cand_list.set_defaults(handler=_candidate_list)

    cand_approve = candidate_sub.add_parser("approve", help="Approve a pending candidate")
    cand_approve.add_argument("candidate_id")
    cand_approve.set_defaults(handler=_candidate_approve)

    cand_reject = candidate_sub.add_parser("reject", help="Reject a pending candidate")
    cand_reject.add_argument("candidate_id")
    cand_reject.add_argument("--reason", required=True)
    cand_reject.set_defaults(handler=_candidate_reject)

    context = subparsers.add_parser("context", help="Build bounded context packets")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    build = context_sub.add_parser("build", help="Build task-relevant context")
    build.add_argument("--project", type=Path, required=True)
    task_group = build.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task")
    task_group.add_argument("--task-file", type=Path)
    build.add_argument("--max-chars", type=int, default=8_000)
    build.add_argument("--json", action="store_true")
    build.set_defaults(handler=_context_build)

    run_cmd = subparsers.add_parser("run", help="Orchestrate an agent run")
    run_cmd.add_argument("--agent", choices=["claude", "codex"], required=True)
    run_cmd.add_argument("--project", type=Path, required=True)
    run_task_group = run_cmd.add_mutually_exclusive_group(required=True)
    run_task_group.add_argument("--task")
    run_task_group.add_argument("--task-file", type=Path)
    run_cmd.add_argument("--resume", help="Vendor session or thread ID")
    run_cmd.add_argument(
        "--execution-policy",
        choices=[v.value for v in AgentExecutionPolicy],
        default="read-only",
    )
    run_cmd.add_argument("--json", action="store_true")
    run_cmd.set_defaults(handler=_agent_run)

    run_show = subparsers.add_parser("run-show", help="Inspect a recorded run")
    run_show.add_argument("run_id")
    run_show.set_defaults(handler=_run_show)

    export_cmd = subparsers.add_parser("export", help="Export Markdown snapshot of project memory")
    export_cmd.add_argument("--project", type=Path, required=True)
    export_cmd.add_argument("--output", type=Path, required=True)
    export_cmd.set_defaults(handler=_export_markdown)

    serve_cmd = subparsers.add_parser("serve", help="Start the local REST API and web shell")
    serve_cmd.add_argument("--port", type=int, default=7532, help="Bind port (default: 7532)")
    serve_cmd.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    serve_cmd.set_defaults(handler=_serve)

    return parser


def _doctor(args: argparse.Namespace) -> None:
    app = create_application()
    db_health = app.doctor.check()
    if args.live:
        agent_health = app.doctor.check_live()
        _print_json({"database": db_health, "agents": agent_health})
    else:
        _print_json(db_health)


def _project_register(args: argparse.Namespace) -> None:
    project = create_application().projects.register(args.path, args.name)
    _print_json(project)


def _memory_add(args: argparse.Namespace) -> None:
    item = create_application().memories.add(
        project_path=args.project,
        kind=MemoryKind(args.kind),
        title=args.title,
        content=args.content,
        scope=MemoryScope(args.scope),
        subject_key=args.subject,
        importance=args.importance,
        volatility=args.volatility,
        confidence=args.confidence,
        pinned=args.pinned,
    )
    _print_json(item)


def _memory_list(args: argparse.Namespace) -> None:
    status = MemoryStatus(args.status) if args.status else None
    page = create_application().memories.list(
        project_path=args.project,
        status=status,
        limit=args.limit,
        cursor=args.cursor,
    )
    _print_json(page)


def _memory_show(args: argparse.Namespace) -> None:
    _print_json(create_application().memories.show(args.memory_id))


def _candidate_list(args: argparse.Namespace) -> None:
    state = CandidateReviewState(args.status) if args.status else None
    cands = create_application().memories.list_candidates(project_path=args.project, state=state)
    _print_json(cands)


def _candidate_approve(args: argparse.Namespace) -> None:
    mem = create_application().memories.approve_candidate(args.candidate_id)
    _print_json(mem)


def _candidate_reject(args: argparse.Namespace) -> None:
    cand = create_application().memories.reject_candidate(args.candidate_id, args.reason)
    _print_json(cand)


def _context_build(args: argparse.Namespace) -> None:
    task = args.task
    if args.task_file:
        task = args.task_file.read_text(encoding="utf-8")
    packet = create_application().contexts.build(
        project_path=args.project, task=task, max_chars=args.max_chars
    )
    if args.json:
        _print_json(packet)
    else:
        print(packet.rendered)


def _agent_run(args: argparse.Namespace) -> None:
    task = args.task
    if args.task_file:
        task = args.task_file.read_text(encoding="utf-8")
    app = create_application()
    run_record, result, summary = app.runs.run(
        project_path=args.project,
        agent=args.agent,
        task=task,
        execution_policy=AgentExecutionPolicy(args.execution_policy),
        resume_vendor_session_id=args.resume,
    )
    if args.json:
        _print_json({"run": run_record, "result": result, "summary": summary})
    else:
        print(f"Run ID: {run_record.id}")
        print(f"Outcome: {result.outcome}")
        print(f"Answer:\n{result.answer}\n")
        print(
            f"Candidates: auto_applied={len(summary.auto_applied)}, "
            f"pending={len(summary.pending)}, "
            f"duplicates={len(summary.duplicates)}, "
            f"blocked_secret={len(summary.blocked_secret)}"
        )


def _run_show(args: argparse.Namespace) -> None:
    _print_json(create_application().runs.show(args.run_id))


def _export_markdown(args: argparse.Namespace) -> None:
    out = create_application().memories.export_markdown(args.project, args.output)
    print(f"Exported memory snapshot to {out}")


def _serve(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError as error:
        print("error[missing_dependency]: uvicorn is not installed.", file=sys.stderr)
        raise SystemExit(1) from error
    host = "127.0.0.1"
    print(f"AI Bridge API  →  http://{host}:{args.port}/docs")
    uvicorn.run(
        "aibridge.api.app:create_api_app",
        host=host,
        port=args.port,
        reload=args.reload,
        factory=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except AIBridgeError as error:
        print(f"error[{error.code}]: {error}", file=sys.stderr)
        return 2
    except PydanticValidationError:
        print("error[invalid_input]: Input failed schema validation.", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error[io_error]: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
