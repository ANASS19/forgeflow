# ForgeFlow engineering instructions

## Purpose and current scope

ForgeFlow is an independent, open-source, local-first workflow execution and
debugging system for API developers. This experimental checkpoint implements
safe loading, schema/DAG/reference validation, static CLI Doctor, async value/assert
execution, HTTP GET/HEAD, SQLite history, and privacy-controlled recording primitives.
Basic bounded HTTP retries are implemented. Replay and execution-time Doctor remain planned.
Only implement the session or task explicitly authorized by the owner.

## Architecture boundaries

- Begin as a modular monolith using a `src/forgeflow` package.
- Create modules when working behavior needs them; avoid empty scaffolding.
- Keep the CLI thin. Future workflow/domain code must not depend on Typer,
  HTTPX, or SQLAlchemy. Future handlers must not directly update database rows.
- The planned MVP actions are HTTP GET/HEAD, literal values, and assertions.
  HTTP HEAD steps must reject JSON-body captures.
- No arbitrary workflow code execution, Python expressions, dynamic imports,
  shell commands, or user-supplied plugins. Development tests may invoke known
  Python and uv executables with explicit argument lists and no shell.
- Future replay must have no live network fallback and must fail clearly when
  required recorded values are unavailable. Do not promise exactly-once execution.
- Do not expose unimplemented commands or describe planned features as working.

## Python and coding standards

- Support Python `>=3.12,<3.13`; preserve the existing interpreter and `.venv`.
- Use uv for project dependencies and keep `uv.lock` ready for version control.
  Do not install global packages, replace uv, or upgrade Python without approval.
- Use type annotations and mypy strict mode. Keep modules small and maintainable,
  with focused responsibilities and meaningful error handling.
- Use Ruff formatting and linting. Prefer standard-library functionality and add
  third-party dependencies only when necessary for the current task.
- Keep the version in `src/forgeflow/__init__.py`; build metadata reads it.
- Add automated tests for every meaningful behavior change, including relevant
  error paths. Tests must assert behavior rather than merely repeat the code.

## Required commands

Run from the repository root:

```console
uv sync --locked --no-python-downloads
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

For an intentional dependency change, use uv to generate the updated lockfile,
then run the checks. Do not manually edit `uv.lock`. The packaging tests must
install the built wheel in an isolated temporary environment and run it outside
the source tree. Report the commands actually executed and their results.

## Security and privacy

- Never commit credentials, personal information, confidential or proprietary
  code/data, environment files, private endpoints, databases, or recordings.
- Use synthetic test fixtures. Never require real credentials or public API calls
  in tests. Dependency installation may access the package index; packaging tests
  run offline after setup.
- Assess headers, query parameters, response metadata, errors, and logs for
  sensitive data. Future recording must exclude full bodies by default and retain
  only minimal safe metadata and explicitly selected, privacy-filtered fields.
- Do not print secrets, raw environment contents, raw request data, exception
  locals, or unsanitized workflow values in diagnostics.
- Do not disable TLS verification, add telemetry, upload recordings, or execute
  untrusted code.
- Ignore rules are only a safeguard; review intended repository artifacts before
  reporting them ready to commit.

## Git and delivery

- Do not modify or delete `.git`, rewrite history, or destroy the existing `.venv`.
- Do not perform remote Git operations, create a repository/remote, push, publish,
  or create a release without explicit authorization for that action.
- Do not make local commits or stage changes unless the owner requests it.
- When the owner authorizes milestone commits/pushes, verify the milestone first,
  preserve legitimate history, and never force-push. Repository instructions alone
  do not authorize publication or account changes.
- Report scope, files, checks, failures/limitations, decisions, and Git status.
  Stop at the authorized session boundary.
