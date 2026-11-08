"""Async DAG execution with durable attempt boundaries and cancellation cleanup."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial

from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError

from forgeflow.domain import TERMINAL, ErrorCode, ForgeFlowError, Outcome, RunResult, State
from forgeflow.engine.http import HttpHandler
from forgeflow.engine.retry import retry_delay
from forgeflow.recorder.privacy import Privacy
from forgeflow.storage.repository import Repository, StorageWorker
from forgeflow.workflow.graph import WorkflowStep, build_graph
from forgeflow.workflow.models import HttpStep, Workflow

type Handler = Callable[[WorkflowStep, dict[str, dict[str, JsonValue]]], Awaitable[Outcome]]
_DEFAULT_PRIVACY = Privacy()


async def execute(
    workflow: Workflow,
    repository: Repository,
    *,
    parent_id: str | None = None,
    handler: Handler | None = None,
    privacy: Privacy = _DEFAULT_PRIVACY,
    progress: Callable[[str, State], None] | None = None,
    delay_policy: Callable[[int, float | None], float] = retry_delay,
) -> RunResult:
    graph = build_graph(workflow)
    selected_handler = handler or HttpHandler(workflow)
    if isinstance(selected_handler, HttpHandler):
        privacy = Privacy((*privacy.secrets, *selected_handler.privacy.secrets))
    steps = {step.id: step for step in workflow.steps}
    states = {step.id: State.PENDING for step in workflow.steps}
    outputs: dict[str, dict[str, JsonValue]] = {}
    worker = StorageWorker()
    tasks: dict[str, asyncio.Task[tuple[Outcome, float | None]]] = {}
    numbers = dict.fromkeys(steps, 0)
    ready_at: dict[str, float] = {}
    run_id: str | None = None
    deadline = 0.0

    async def attempt(name: str, number: int) -> tuple[Outcome, float | None]:
        step = steps[name]
        await worker.call(lambda: repository.start_attempt(run_id or "", name, number))
        started = time.monotonic()
        try:
            async with asyncio.timeout(
                step.attempt_timeout_seconds or workflow.defaults.attempt_timeout_seconds
            ):
                result = await selected_handler(step, outputs)
        except TimeoutError:
            result = Outcome(State.TIMED_OUT, code=ErrorCode.TIMEOUT, retryable=True)
        except ForgeFlowError as error:
            result = Outcome(State.FAILED, code=error.code)
        except asyncio.CancelledError:
            raise
        except Exception:
            result = Outcome(State.FAILED, code=ErrorCode.INTERNAL)
        delay: float | None = None
        if isinstance(step, HttpStep) and result.retryable and number < step.retry.max_attempts:
            proposed = delay_policy(number, result.retry_after)
            if time.monotonic() + proposed < deadline:
                delay = proposed
        await worker.call(
            lambda: repository.finish_attempt(
                run_id or "",
                name,
                number,
                result,
                time.monotonic() - started,
                privacy,
                retry_delay=delay,
            )
        )
        return result, delay

    try:
        run_id = await worker.call(
            lambda: repository.create_run(workflow, privacy, parent_id=parent_id)
        )
        terminal_state = State.SUCCEEDED
        deadline = time.monotonic() + workflow.execution.timeout_seconds
        try:
            async with asyncio.timeout(workflow.execution.timeout_seconds):
                while any(state not in TERMINAL for state in states.values()):
                    for name in graph.order:
                        if states[name] not in {State.PENDING, State.RETRY_WAIT}:
                            continue
                        if ready_at.get(name, 0) > time.monotonic():
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
                                numbers[name] += 1
                                tasks[name] = asyncio.create_task(attempt(name, numbers[name]))
                        if progress and states[name] != State.PENDING:
                            progress(name, states[name])
                    waiting = [
                        when for name, when in ready_at.items() if states[name] == State.RETRY_WAIT
                    ]
                    pause = max(0.0, min(waiting) - time.monotonic()) if waiting else None
                    if tasks:
                        done, _ = await asyncio.wait(
                            tasks.values(),
                            return_when=asyncio.FIRST_COMPLETED,
                            timeout=pause if len(tasks) < workflow.execution.concurrency else None,
                        )
                        for name in list(tasks):
                            if tasks[name] not in done:
                                continue
                            result, delay = tasks.pop(name).result()
                            states[name] = State.RETRY_WAIT if delay is not None else result.state
                            if delay is not None:
                                ready_at[name] = time.monotonic() + delay
                            else:
                                outputs[name] = result.outputs
                            if progress:
                                progress(name, states[name])
                    elif pause is not None:
                        await asyncio.sleep(pause)
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
