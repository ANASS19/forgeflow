# Contributing to ForgeFlow

ForgeFlow is an experimental workflow debugging project. Start with a small, verifiable
change, and keep documentation clear about working and planned functionality.

## Environment

Use Python 3.12 and uv. The checkout pins Python 3.12.10. From the repository root:

```console
uv sync --locked --no-python-downloads
```

This reuses the local `.venv`. Do not recreate an existing environment or install
project dependencies globally. If the required Python interpreter is unavailable,
install it separately before running this command; automatic Python downloads
are disabled by the documented setup command.

Typer, Pydantic v2, PyYAML, SQLAlchemy, Alembic, and HTTPX are the direct runtime
dependencies. pytest, pytest-asyncio, Ruff, mypy, PyYAML typing stubs, and Hatchling
are development dependencies. Hatchling is also the PEP 517 build backend and
is installed locally so packaging tests can build without network access.

## Required checks

```console
uv lock --check
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --no-sources
uv run --locked forgeflow --help
uv run --locked python -m forgeflow --version
uv run --locked python examples/demo.py
```

The tests require uv on `PATH` and the dependencies installed by `uv sync`.
Packaging tests use temporary directories, build an sdist and a wheel from that
sdist, sync runtime dependencies directly from `uv.lock` into a temporary environment,
install only the wheel into that environment, and run both CLI entry points
and the workflow-loading API outside the checkout. They
run offline using the populated uv cache; they do not reuse development
site-packages or modify the checkout's `.venv`.

Ruff owns formatting and import ordering. To apply formatting intentionally:

```console
uv run --locked ruff format .
```

## Changes and dependencies

- Follow [AGENTS.md](AGENTS.md), use strict typing, and keep modules small.
- Add tests for every meaningful behavior change, including failure behavior.
- Keep dependency additions necessary and explain their purpose.
- Use uv to update `uv.lock`; never edit it by hand.
- Dependency changes must include the corresponding `pyproject.toml` and lockfile
  changes. Do not upgrade unrelated packages as part of another task.
- Keep package version changes in `src/forgeflow/__init__.py`; Hatchling reads it.
- Keep schema migrations immutable; create a new revision for future changes.
- Use temporary storage in tests. Do not create history in the repository root.
- Document any user-facing behavior change. Do not add placeholders for features
  that are not part of the current task.

## Privacy and publication

Use synthetic fixtures and sanitized bug reports. Do not include credentials,
personal information, proprietary code, private endpoints, execution databases,
or raw recordings. Do not post sensitive material in public issues.

Submitting a contribution is under the project's Apache-2.0 license; contributors
retain their applicable copyright. Automated agents must obtain explicit task
authorization before remote Git operations, publishing, or releases. Local
commits also require authorization when working on behalf of the owner.

See [ROADMAP.md](ROADMAP.md) and existing GitHub issues for planned work. Retry
scheduling and replay are not current features. Keep implementation PRs focused
on one tested behavior, describe remaining limitations, and link the relevant issue.
