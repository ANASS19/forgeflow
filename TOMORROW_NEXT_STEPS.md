# Next development session

## Current checkpoint

- HTTP GET/HEAD executes with HTTPX, isolated clients, TLS verification, bounded
  UTF-8 JSON captures, secret preflight, and sanitized errors/logs.
- Basic transient-failure retries are opt-in: one attempt by default, at most five.
  Jitter and capped Retry-After waits release concurrency slots and respect deadlines.
- Existing pure workflows, dependency failure propagation, and SQLite history remain supported.
- No new Flight Recorder, replay, cloud, or distributed-worker work was started.
- HTTP feature baseline: `5710421`. This note accompanies the subsequent retry
  checkpoint; use `git log -1 --oneline` for its exact commit.

## Exact next tasks

1. Read AGENTS.md, inspect `git status --short --branch`, and confirm local main
   matches origin/main before editing. Review the latest GitHub Actions result.
2. Harden HTTP error normalization for malformed Unicode/query values and stream
   aborts. Add tests that verify safe error codes, closed responses, and no sensitive logs.
3. Expand deterministic retry timing tests around exact deadline boundaries,
   malformed/long Retry-After headers, cancellation during storage writes, and
   partial-body timeouts. Preserve max-attempt bounds and one attempt by default.
4. Start focused storage-failure/process-termination tests from issue #6. Prove
   an uncommitted attempt never dispatches and a failed recorder stops new work.
5. Commit and push only verified changes; do not start replay or unrelated features
   without a new scoped request.

## Verification commands

```console
uv sync --locked --no-python-downloads
uv lock --check
uv run pytest tests/test_http.py tests/test_http_integration.py tests/test_retry.py tests/test_execution.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run mypy
uv build
uv run python examples/demo.py
uv run forgeflow validate examples/http-local.yaml
```

Local HTTP smoke check, using two terminals:

```console
uv run python -m http.server 8000 --bind 127.0.0.1 --directory examples/http-api
```

```console
uv run forgeflow run examples/http-local.yaml --data-dir .forgeflow --json
uv run forgeflow history --data-dir .forgeflow --json
```

Stop the fixture server with Ctrl+C. `.forgeflow/` is local ignored data and must
never be staged. Tests use synthetic loopback APIs and do not need public services
or real credentials. Use the authenticated GitHub CLI to verify any push and CI;
never force-push or rewrite history.
