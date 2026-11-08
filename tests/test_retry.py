"""Exact attempt budgets, temporary failures, deadlines, and released retry slots."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from forgeflow.domain import Outcome, State
from forgeflow.engine.http import HttpHandler
from forgeflow.engine.retry import parse_retry_after, retry_delay
from forgeflow.engine.runner import execute
from forgeflow.storage.repository import Repository
from forgeflow.workflow import parse_workflow
from forgeflow.workflow.graph import WorkflowStep
from forgeflow.workflow.models import Workflow


def workflow(max_attempts: int = 3, *, independent: bool = False) -> Workflow:
    steps: list[dict[str, object]] = [
        {
            "id": "fetch",
            "type": "http",
            "retry": {"max_attempts": max_attempts},
            "request": {"method": "GET", "url": "https://example.test/health"},
            "capture": {"value": "/value"},
        },
        {
            "id": "check",
            "type": "assert",
            "needs": ["fetch"],
            "left": {"ref": "fetch.outputs.value"},
            "op": "eq",
            "right": {"literal": 7},
        },
    ]
    if independent:
        steps.append({"id": "independent", "type": "value", "values": {"n": 1}})
    return parse_workflow(
        json.dumps({"schema_version": 1, "name": "retries", "steps": steps}).encode()
    )


def no_delay(attempt: int, retry_after: float | None) -> float:
    return 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
async def test_temporary_status_then_success(tmp_path: Path, status: int) -> None:
    source = workflow()
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status if calls == 1 else 200, json={"value": 7})

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=handler, delay_policy=no_delay)
        attempts = [
            item for item in repository.snapshot(result.id).attempts if item.step_id == "fetch"
        ]
    assert result.state == State.SUCCEEDED and calls == 2
    assert [item.number for item in attempts] == [1, 2]
    assert attempts[0].state == State.FAILED and attempts[0].retry_delay == 0
    assert attempts[1].state == State.SUCCEEDED and attempts[1].retry_delay is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(503, 3), (404, 1), (500, 1)])
async def test_exact_attempt_cap_and_permanent_failure(
    tmp_path: Path, status: int, expected: int
) -> None:
    source = workflow()
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=handler, delay_policy=no_delay)
        attempts = repository.snapshot(result.id).attempts
    assert calls == expected == len(attempts)
    assert result.steps["check"] == State.SKIPPED
    assert attempts[-1].retry_delay is None


@pytest.mark.asyncio
async def test_default_attempt_count_is_one(tmp_path: Path) -> None:
    source = workflow(1)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        await execute(source, repository, handler=handler, delay_policy=no_delay)
    assert calls == 1


@pytest.mark.asyncio
async def test_backoff_releases_the_execution_slot(tmp_path: Path) -> None:
    source = workflow(independent=True)
    source.execution.concurrency = 1
    starts: list[str] = []
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, json={"value": 7})

    live = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))

    async def handler(step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
        starts.append(step.id)
        return await live(step, outputs)

    with Repository(tmp_path, writable=True) as repository:
        result = await execute(
            source, repository, handler=handler, delay_policy=lambda n, after: 0.1
        )
    assert result.state == State.SUCCEEDED
    assert starts == ["fetch", "independent", "fetch", "check"]


@pytest.mark.asyncio
async def test_retry_after_does_not_outlive_workflow_budget(tmp_path: Path) -> None:
    source = workflow()
    source.execution.timeout_seconds = 1
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "30"})

    live = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=live)
        assert repository.snapshot(result.id).attempts[0].retry_delay is None
    assert calls == 1 and result.state == State.FAILED


@pytest.mark.asyncio
async def test_cancellation_during_backoff_sends_no_next_request(tmp_path: Path) -> None:
    source = workflow()
    waiting = asyncio.Event()
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    live = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))

    def progress(name: str, state: State) -> None:
        if state == State.RETRY_WAIT:
            waiting.set()

    with Repository(tmp_path, writable=True) as repository:
        task = asyncio.create_task(
            execute(
                source, repository, handler=live, delay_policy=lambda n, after: 5, progress=progress
            )
        )
        async with asyncio.timeout(5):
            await waiting.wait()
        task.cancel()
        result = await task
        assert len(repository.snapshot(result.id).attempts) == 1
    assert result.state == State.CANCELLED and calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["connection", "timeout"])
async def test_connection_and_attempt_timeout_can_retry(tmp_path: Path, kind: str) -> None:
    source = workflow(2)
    source.steps[0].attempt_timeout_seconds = 0.01
    calls = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if kind == "connection":
                raise httpx.ConnectError("SYNTHETIC_NETWORK_ERROR")
            await asyncio.sleep(0.05)
        return httpx.Response(200, json={"value": 7})

    live = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=live, delay_policy=no_delay)
    assert result.state == State.SUCCEEDED and calls == 2


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0", 0),
        ("5", 5),
        ("1000", 30),
        ("-1", None),
        ("1.5", None),
        ("private-invalid-header", None),
        (None, None),
    ],
)
def test_retry_after_delta(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_retry_after_date_and_jitter_bounds() -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    assert parse_retry_after("Sun, 08 Nov 2026 12:00:10 GMT", now=now) == 10
    assert parse_retry_after("Sun, 08 Nov 2026 11:59:00 GMT", now=now) == 0
    for attempt in range(1, 6):
        assert 0 <= retry_delay(attempt) <= min(5, 0.5 * 2 ** (attempt - 1))
        assert 10 <= retry_delay(attempt, 10) <= 30
