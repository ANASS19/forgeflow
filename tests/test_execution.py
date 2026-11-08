"""Durability, DAG scheduling, cancellation, and pure-step semantics."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import JsonValue
from sqlalchemy import text

from forgeflow.domain import ErrorCode, ForgeFlowError, Outcome, State
from forgeflow.engine.pure import execute_pure, json_equal
from forgeflow.engine.runner import execute
from forgeflow.recorder.privacy import Privacy
from forgeflow.storage.repository import Repository
from forgeflow.workflow import parse_workflow
from forgeflow.workflow.graph import WorkflowStep
from forgeflow.workflow.models import AssertStep, ValueStep


def _workflow(*, failing: bool = False) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "name": "execution",
            "steps": [
                {"id": "seed", "type": "value", "values": {"n": 1}},
                {
                    "id": "check",
                    "type": "assert",
                    "needs": ["seed"],
                    "left": {"ref": "seed.outputs.n"},
                    "op": "eq",
                    "right": {"literal": 2 if failing else 1},
                },
                {"id": "child", "type": "value", "needs": ["check"], "values": {"n": 2}},
                {"id": "independent", "type": "value", "values": {"n": 3}},
            ],
        }
    ).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", [True, False])
async def test_durable_run_and_failure_propagation(tmp_path: Path, failing: bool) -> None:
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(parse_workflow(_workflow(failing=failing)), repository)
        snapshot = repository.snapshot(result.id)
        assert result.state == (State.FAILED if failing else State.SUCCEEDED)
        assert snapshot.steps["child"] == (State.SKIPPED if failing else State.SUCCEEDED)
        assert snapshot.steps["independent"] == State.SUCCEEDED
        assert snapshot.causes["child"] == (["check"] if failing else [])
        assert [event.sequence for event in snapshot.events] == list(
            range(1, len(snapshot.events) + 1)
        )
    with Repository(tmp_path) as reader:
        assert reader.history()[0]["id"] == result.id
        assert reader.snapshot(result.id).state == result.state


@pytest.mark.asyncio
async def test_dependency_aware_concurrency(tmp_path: Path) -> None:
    active = peak = 0
    completed: set[str] = set()
    gate = asyncio.Event()

    async def handler(step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
        nonlocal active, peak
        assert set(step.needs) <= completed
        active += 1
        peak = max(peak, active)
        if peak == 2:
            gate.set()
        await gate.wait()
        active -= 1
        completed.add(step.id)
        assert isinstance(step, (ValueStep, AssertStep))
        return execute_pure(step, outputs)

    workflow = parse_workflow(_workflow())
    workflow.execution.concurrency = 2
    with Repository(tmp_path, writable=True) as repository:
        async with asyncio.timeout(5):
            result = await execute(workflow, repository, handler=handler)
    assert result.state == State.SUCCEEDED
    assert peak == 2


@pytest.mark.asyncio
async def test_cancellation_is_persisted(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def handler(step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
        started.set()
        await asyncio.sleep(30)
        return Outcome(State.SUCCEEDED)

    with Repository(tmp_path, writable=True) as repository:
        task = asyncio.create_task(
            execute(parse_workflow(_workflow()), repository, handler=handler)
        )
        await started.wait()
        task.cancel()
        result = await task
        assert result.state == State.CANCELLED
        assert all(state in {State.CANCELLED, State.SUCCEEDED} for state in result.steps.values())
        assert all(
            attempt.state != State.RUNNING for attempt in repository.snapshot(result.id).attempts
        )


def test_lock_exclusion_and_read_concurrency(tmp_path: Path) -> None:
    with Repository(tmp_path, writable=True):
        with pytest.raises(ForgeFlowError) as error:
            Repository(tmp_path, writable=True)
        assert error.value.code == ErrorCode.BUSY
        with Repository(tmp_path) as reader:
            assert reader.history() == []


def test_recovery_and_linked_runs(tmp_path: Path) -> None:
    workflow = parse_workflow(_workflow())
    with Repository(tmp_path, writable=True) as repository:
        source = repository.create_run(workflow, Privacy())
        repository.start_attempt(source, "seed", 1)
    with Repository(tmp_path, writable=True) as repository:
        with pytest.raises(ForgeFlowError) as error:
            repository.create_run(workflow, Privacy())
        assert error.value.code == ErrorCode.RECOVERY
        assert repository.recover() == [source]
        assert repository.snapshot(source).attempts[0].state == State.INTERRUPTED
        linked = repository.create_run(workflow, Privacy(), parent_id=source)
        assert repository.snapshot(linked).parent_id == source
        assert repository.snapshot(linked).values == {}


def test_unsupported_database_revision_is_not_recreated(tmp_path: Path) -> None:
    with Repository(tmp_path, writable=True) as repository:
        with repository.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='future'"))
    with pytest.raises(ForgeFlowError) as error:
        Repository(tmp_path, writable=True)
    assert error.value.code == ErrorCode.SCHEMA


@pytest.mark.parametrize(
    "left,right,equal",
    [(True, 1, False), ([True], [1], False), ({"n": True}, {"n": 1}, False), (1, 1.0, True)],
)
def test_json_equality(left: JsonValue, right: JsonValue, equal: bool) -> None:
    assert json_equal(left, right) is equal


def test_privacy_and_recording_plan(tmp_path: Path) -> None:
    secret = "SYNTHETIC_RUNTIME_CANARY"
    workflow = parse_workflow(
        json.dumps(
            {
                "schema_version": 1,
                "name": "privacy",
                "steps": [
                    {
                        "id": "seed",
                        "type": "value",
                        "values": {"safe": 1, "payload": {"token": secret}},
                    }
                ],
            }
        ).encode()
    )
    with Repository(tmp_path, writable=True) as repository:
        run_id = repository.create_run(workflow, Privacy((secret,)))
        repository.start_attempt(run_id, "seed", 1)
        repository.finish_attempt(
            run_id,
            "seed",
            1,
            Outcome(State.SUCCEEDED, {"payload": secret}),
            0.0,
            Privacy((secret,)),
        )
        snapshot = repository.snapshot(run_id)
        assert snapshot.values["seed"]["payload"] == {"availability": "redacted"}
    assert all(
        secret.encode() not in path.read_bytes() for path in tmp_path.glob("history.sqlite3*")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_deadline", [False, True])
async def test_timeouts_are_durable(tmp_path: Path, workflow_deadline: bool) -> None:
    workflow = parse_workflow(_workflow())
    workflow.execution.timeout_seconds = 1 if workflow_deadline else 300
    workflow.defaults.attempt_timeout_seconds = 30 if workflow_deadline else 0.02

    async def waiting(step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
        await asyncio.sleep(10)
        return Outcome(State.SUCCEEDED)

    with Repository(tmp_path, writable=True) as repository:
        result = await execute(workflow, repository, handler=waiting)
        assert result.state == (State.TIMED_OUT if workflow_deadline else State.FAILED)
        snapshot = repository.snapshot(result.id)
        assert all(state not in {State.PENDING, State.RUNNING} for state in snapshot.steps.values())
        assert all(attempt.state != State.RUNNING for attempt in snapshot.attempts)
