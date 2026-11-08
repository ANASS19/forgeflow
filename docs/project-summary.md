# Project submission summary

- **Project:** ForgeFlow
- **Repository:** https://github.com/ANASS19/forgeflow
- **Status:** Independently maintained, open-source, pre-alpha software under active development.
- **License:** Apache-2.0

## Language and stack

Python 3.12, uv, Typer, Pydantic v2, PyYAML, asyncio, SQLite, SQLAlchemy,
Alembic, HTTPX, pytest, pytest-asyncio, Ruff, mypy, and GitHub Actions.

## Current functionality and problem

ForgeFlow helps API developers define small YAML workflow graphs, catch
configuration/dependency mistakes, and understand step-level outcomes locally.
It currently validates bounded YAML input, builds explicit dependency graphs,
detects cycles, validates output references, and provides a static Workflow Doctor.
Its async engine executes built-in value/assert and HTTP GET/HEAD steps with dependency-aware
concurrency, failure propagation, deadlines, and local SQLite history.
Inspection exposes attempt error codes, skipped-dependant causes, and recording
availability. A runnable local demonstration exercises real success and failure.

## Technical challenges

- Rejecting unsafe YAML constructs before object construction while bounding input resources.
- Producing useful errors without echoing secrets or private workflow values.
- Reconciling concurrent execution with atomic database state/evidence transitions.
- Preserving explicit interruption and cancellation states without false reliability claims.
- Verifying wheel installation and CLI behavior outside an editable source checkout.

## Planned development

The next intended contributions are bounded and
observable retries, stronger failure-recovery testing, execution-time Doctor
diagnostics, and a versioned Flight Recorder with offline replay. Replay must
reject missing evidence and must never repeat a network request as a fallback.

## Trade-offs and limitations

The modular monolith and local SQLite store keep deployment simple. One active
writer per database simplifies ownership and recovery, while steps may run
concurrently. Strict YAML and built-in actions trade flexibility for a bounded
execution model. Stored values are plaintext and privacy filtering is heuristic.
Retries, replay, distributed workers, and a web UI are not current
features. This checkpoint is not a production or exactly-once reliability claim.
