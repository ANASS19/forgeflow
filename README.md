# ForgeFlow

ForgeFlow is an independent, open-source project building a local-first workflow
execution and debugging system for API developers.

## Current status

**Project foundation: `0.1.0.dev0`.** The package is installable and provides a
typed Typer CLI with help and version information. Automated tests cover package
imports, CLI behavior, and installation of a built wheel in an isolated environment.

```text
forgeflow --help
forgeflow --version
python -m forgeflow --help
```

Running `forgeflow` without arguments also displays help. Workflow parsing,
validation, execution, history, Doctor diagnostics, and replay are **planned**;
they are not implemented in this release.

## Local installation

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/). Python 3.13 and later
are not supported by the initial release. `.python-version` selects Python 3.12.10
for this checkout.

From the repository directory:

```console
uv sync --locked --no-python-downloads
uv run --locked forgeflow --help
uv run --locked forgeflow --version
```

This installs the package and development dependencies in the local `.venv`.
An existing compatible `.venv` is reused; no global packages are installed. The
first installation requires access to the package index. No workflow or runtime
data directory is created by the current CLI.

## Planned MVP

The first MVP is intended to support YAML dependency graphs, HTTP GET/HEAD,
built-in value and assertion steps, bounded retries, persistent history, and
actionable Workflow Doctor diagnostics. An Execution Flight Recorder will retain
minimal metadata and explicitly selected response fields. Offline replay will
fail clearly if required recorded values are unavailable and will never fall
back to live requests. HTTP HEAD steps will not support JSON-body captures.

These are design boundaries, not claims of working functionality. There is no
arbitrary-code or subprocess workflow action planned for the MVP, and no
exactly-once execution guarantee.

## Package structure

- `src/forgeflow/__init__.py`: package version, also used by the build backend.
- `src/forgeflow/cli.py`: Typer application and package-information options.
- `src/forgeflow/__main__.py`: `python -m forgeflow` entry point.
- `tests/`: CLI, import, distribution metadata, and isolated-install checks.

Future workflow, execution, recording, and storage modules will be added when
their behavior is implemented. The intended architecture is a modular monolith.

## Development

```console
uv lock --check
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv build --no-sources
```

Build artifacts are written to `dist/`. The test suite also builds an sdist and
wheel, installs the wheel with locked runtime dependencies into a temporary virtual
environment, and exercises it outside the checkout. Those packaging tests use
uv's local cache in offline mode after the initial dependency installation.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development details and
[AGENTS.md](AGENTS.md) for engineering boundaries.

## Security and privacy

Never commit credentials, confidential data, personal data, private recordings,
or environment files. Use synthetic data in tests and examples. The current CLI
does not perform network requests, resolve environment secrets, or execute
workflows. Local development installation may download dependencies.

## License

Apache License 2.0. See [LICENSE](LICENSE).

Copyright 2026 ForgeFlow contributors.
