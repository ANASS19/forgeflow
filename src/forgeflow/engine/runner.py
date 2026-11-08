"""Async DAG execution with durable attempt boundaries and cancellation cleanup."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial

from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError

from forgeflow.domain import TERMINAL, ErrorCode, ForgeFlowError, Outcome, RunResult, State
from forgeflow.engine.pure import execute_pure
from forgeflow.recorder.privacy import Privacy
from forgeflow.storage.repository import Repository, StorageWorker
from forgeflow.workflow.graph import WorkflowStep, build_graph
from forgeflow.workflow.models import AssertStep, HttpStep, ValueStep, Workflow

type Handler = Callable[[WorkflowStep, dict[str, dict[str, JsonValue]]], Awaitable[Outcome]]
_DEFAULT_PRIVACY = Privacy()


def ensure_supported(workflow: Workflow) -> None:
    """Refuse planned actions before initializing a run or dispatching any work."""
    if any(isinstance(step, HttpStep) for step in workflow.steps):
        raise ForgeFlowError(ErrorCode.ACTION_UNAVAILABLE)


async def default_handler(step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
    if isinstance(step, (ValueStep, AssertStep)):
        return execute_pure(step, outputs)
    raise ForgeFlowError(ErrorCode.ACTION_UNAVAILABLE)


async def execute(
    workflow: Workflow,
    repository: Repository,
    *,
    parent_id: str | None = None,
    handler: Handler = default_handler,
    privacy: Privacy = _DEFAULT_PRIVACY,
    progress: Callable[[str, State], None] | None = None,
) -> RunResult:
    graph = build_graph(workflow)
    if handler is default_handler:
        ensure_supported(workflow)
    steps = {step.id: step for step in workflow.steps}
    states = {step.id: State.PENDING for step in workflow.steps}
    outputs: dict[str, dict[str, JsonValue]] = {}
    worker = StorageWorker()
    tasks: dict[str, asyncio.Task[Outcome]] = {}
    run_id: str | None = None

    async def attempt(name: str) -> Outcome:
        step = steps[name]
        await worker.call(lambda: repository.start_attempt(run_id or "", name, 1))
        started = time.monotonic()
        try:
            async with asyncio.timeout(
                step.attempt_timeout_seconds or workflow.defaults.attempt_timeout_seconds
            ):
                result = await handler(step, outputs)
        except TimeoutError:
            result = Outcome(State.TIMED_OUT, code=ErrorCode.TIMEOUT, retryable=True)
        except ForgeFlowError as error:
            result = Outcome(State.FAILED, code=error.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            result = Outcome(State.FAILED, code=ErrorCode.INTERNAL)
        await worker.call(
            lambda: repository.finish_attempt(
                run_id or "", name, 1, result, time.monotonic() - started, privacy
            )
        )
        return result

    try:
        run_id = await worker.call(
            lambda: repository.create_run(workflow, privacy, parent_id=parent_id)
        )
        terminal_state = State.SUCCEEDED
        try:
            async with asyncio.timeout(workflow.execution.timeout_seconds):
                while any(state not in TERMINAL for state in states.values()):
                    for name in graph.order:
                        if states[name] != State.PENDING:
                            continue
                        parents = graph.predecessors[name]
                        failed = [
                            parent
                            for parent in parents
                            if states[parent] in TERMINAL and states[parent] != State.SUCCEEDED
                        ]
                        if failed:
                            await worker.call(partial(repository.skip, run_id or "", name, failed))
                            states[name] = State.SKIPPED
                        elif all(states[parent] == State.SUCCEEDED for parent in parents):
                            if len(tasks) < workflow.execution.concurrency:
                                states[name] = State.RUNNING
                                tasks[name] = asyncio.create_task(attempt(name))
                        if progress and states[name] != State.PENDING:
                            progress(name, states[name])
                    if tasks:
                        done, _ = await asyncio.wait(
                            tasks.values(), return_when=asyncio.FIRST_COMPLETED
                        )
                        for name in list(tasks):
                            if tasks[name] not in done:
                                continue
                            result = tasks.pop(name).result()
                            states[name] = result.state
                            outputs[name] = result.outputs
                            if progress:
                                progress(name, result.state)
                if any(state != State.SUCCEEDED for state in states.values()):
                    terminal_state = State.FAILED
        except TimeoutError:
            terminal_state = State.TIMED_OUT
        except asyncio.CancelledError:
            terminal_state = State.CANCELLED
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
        await worker.call(lambda: repository.finish_run(run_id or "", terminal_state))
        snapshot = await worker.call(lambda: repository.snapshot(run_id or ""))
        return RunResult(run_id, terminal_state, snapshot.steps)
    except (SQLAlchemyError, OSError):
        raise ForgeFlowError(ErrorCode.STORAGE) from None
    finally:
        for task in tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        await worker.close()
