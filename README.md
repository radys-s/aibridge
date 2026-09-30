# AI Bridge

AI Bridge is a local-first, provider-independent memory and context layer for AI
development agents. The current milestone is deliberately small: it stores durable project
knowledge, retrieves only task-relevant items, and produces a bounded context packet.

## Quick start

```powershell
uv sync
uv run aibridge doctor
uv run aibridge project register C:\path\to\project
uv run aibridge memory add --project C:\path\to\project --kind learning `
  --title "Refresh token rotation" `
  --content "Refresh tokens are rotated after every successful use."
uv run aibridge context build --project C:\path\to\project --task "Update authentication"
```

By default the database is stored in the operating system's application-data directory. A
production `AIBRIDGE_DATA_DIR` override must be absolute and is rejected when it resolves inside a
Git repository, the AI Bridge source tree, or a known cloud-sync directory. Tests create their
databases under a unique operating-system temp directory.

Context output is a versioned JSON data document. It always includes the complete objective and a
security notice that treats retrieved memory as untrusted data. If those mandatory fields and the
explicit omitted-item metadata do not fit, context creation fails instead of truncating them.

`memory list` uses bounded cursor pagination:

```powershell
uv run aibridge memory list --project C:\path\to\project --limit 25
uv run aibridge memory list --project C:\path\to\project --limit 25 --cursor <next_cursor>
```

Expected application errors are printed as `error[stable_code]: message` and return exit code 2
without a traceback. Manual memory containing a detected credential is rejected before any
revision, FTS row, provenance, or event is persisted.

## Verification

Use an OS-temp uv cache on this Windows machine; do not create cache or smoke databases in the
repository:

```powershell
$env:UV_CACHE_DIR = Join-Path ([IO.Path]::GetTempPath()) 'aibridge-uv-cache'
$env:UV_PROJECT_ENVIRONMENT = Join-Path ([IO.Path]::GetTempPath()) 'aibridge-verify-venv'
uv sync --locked
uv build
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

See [docs/PLAN.md](docs/PLAN.md), [docs/STATUS.md](docs/STATUS.md), and the architecture decisions
in [docs/adr](docs/adr).
