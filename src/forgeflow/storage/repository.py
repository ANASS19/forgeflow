"""Atomic execution transitions and recorder writes, owned by one writer command."""

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from forgeflow.domain import TERMINAL, ErrorCode, ForgeFlowError, Outcome, State
from forgeflow.recorder.privacy import Privacy, encoded, recording_plan
from forgeflow.storage.database import open_database
from forgeflow.storage.locking import writer_lock
from forgeflow.storage.schema import Attempt, Event, RecordedValue, Run, StepRun
from forgeflow.workflow.models import Workflow


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class AttemptData:
    step_id: str
    number: int
    state: State
    code: ErrorCode | None
    status_code: int | None
    duration: float
    retryable: bool
    retry_delay: float | None


@dataclass(frozen=True)
class EventData:
    sequence: int
    kind: str
    step_id: str | None
    attempt: int | None
    payload: dict[str, JsonValue]


@dataclass(frozen=True)
class Snapshot:
    id: str
    name: str
    parent_id: str | None
    mode: str
    state: State
    plan: dict[str, JsonValue]
    steps: dict[str, State]
    causes: dict[str, list[str]]
    attempts: tuple[AttemptData, ...]
    values: dict[str, dict[str, dict[str, JsonValue]]]
    events: tuple[EventData, ...]


class Repository(AbstractContextManager["Repository"]):
    def __init__(self, directory: Path, *, writable: bool = False) -> None:
        self._lock: AbstractContextManager[None] | None = (
            writer_lock(directory) if writable else None
        )
        self.writable = writable
        if self._lock is not None:
            self._lock.__enter__()
        try:
            path = directory / "history.sqlite3"
            if not writable and not path.is_file():
                raise ForgeFlowError(ErrorCode.NOT_FOUND)
            self.engine = open_database(path, writable=writable)
        except BaseException:
            if self._lock is not None:
                self._lock.__exit__(None, None, None)
            raise

    def __enter__(self) -> "Repository":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.engine.dispose()
        if self._lock is not None:
            self._lock.__exit__(exc_type, exc, traceback)

    def _session(self) -> Session:
        if not self.writable:
            raise ForgeFlowError(ErrorCode.STORAGE)
        return Session(self.engine, expire_on_commit=False)

    @staticmethod
    def _run(session: Session, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise ForgeFlowError(ErrorCode.NOT_FOUND)
        return run

    @staticmethod
    def _event(
        session: Session,
        run: Run,
        kind: str,
        step_id: str | None = None,
        attempt: int | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        data = encoded(payload or {})
        run.recorded_bytes += len(data.encode())
        run.event_count += 1
        if run.recorded_bytes > 16 * 1024 * 1024 or run.event_count > 10_000:
            raise ForgeFlowError(ErrorCode.STORAGE_LIMIT)
        session.add(
            Event(
                run_id=run.id,
                sequence=run.event_count,
                kind=kind,
                step_id=step_id,
                attempt=attempt,
                timestamp=now(),
                payload=data,
            )
        )

    def create_run(
        self,
        workflow: Workflow,
        privacy: Privacy,
        *,
        parent_id: str | None = None,
        mode: str = "live",
    ) -> str:
        with self._session() as session, session.begin():
            if session.scalar(select(Run.id).where(Run.state.in_(["RUNNING", "PENDING"]))):
                raise ForgeFlowError(ErrorCode.RECOVERY)
            if parent_id:
                parent = self._run(session, parent_id)
                if State(parent.state) not in TERMINAL:
                    raise ForgeFlowError(ErrorCode.PARENT)
            run_id = str(uuid4())
            plan = encoded(recording_plan(workflow, privacy))
            run = Run(
                id=run_id,
                name=workflow.name,
                parent_id=parent_id,
                mode=mode,
                state=State.RUNNING,
                created=now(),
                plan=plan,
                event_count=0,
                recorded_bytes=len(plan.encode()),
            )
            session.add(run)
            session.flush()
            for position, step in enumerate(workflow.steps):
                session.add(
                    StepRun(
                        run_id=run_id,
                        step_id=step.id,
                        kind=step.type,
                        position=position,
                        state=State.PENDING,
                    )
                )
            self._event(session, run, "run_started", payload={"mode": mode})
            return run_id

    def start_attempt(self, run_id: str, step_id: str, number: int) -> None:
        with self._session() as session, session.begin():
            run = self._run(session, run_id)
            step = session.get(StepRun, (run_id, step_id))
            if step is None or State(step.state) not in {State.PENDING, State.RETRY_WAIT}:
                raise ForgeFlowError(ErrorCode.STORAGE)
            if run.state != State.RUNNING:
                raise ForgeFlowError(ErrorCode.STORAGE)
            step.state = State.READY
            self._event(session, run, "step_ready", step_id)
            step.state = State.RUNNING
            session.add(Attempt(run_id=run_id, step_id=step_id, number=number, state=State.RUNNING))
            self._event(session, run, "attempt_started", step_id, number)

    def finish_attempt(
        self,
        run_id: str,
        step_id: str,
        number: int,
        outcome: Outcome,
        duration: float,
        privacy: Privacy,
        retry_delay: float | None = None,
    ) -> None:
        with self._session() as session, session.begin():
            run = self._run(session, run_id)
            step = session.get(StepRun, (run_id, step_id))
            attempt = session.scalar(
                select(Attempt).where(
                    Attempt.run_id == run_id, Attempt.step_id == step_id, Attempt.number == number
                )
            )
            if step is None or attempt is None or attempt.state != State.RUNNING:
                raise ForgeFlowError(ErrorCode.STORAGE)
            attempt.state = outcome.state
            attempt.code = outcome.code
            attempt.duration = duration
            attempt.status_code = outcome.status_code
            attempt.retryable = outcome.retryable
            attempt.retry_delay = retry_delay
            step.state = State.RETRY_WAIT if retry_delay is not None else outcome.state
            if outcome.state == State.SUCCEEDED:
                recorded = {
                    name: privacy.record(value, name=name)
                    for name, value in outcome.outputs.items()
                }
                if len(encoded(recorded).encode()) > 256 * 1024:
                    recorded = {name: {"availability": "too_large"} for name in recorded}
                for name, item in recorded.items():
                    value = encoded(item["value"]) if item["availability"] == "present" else None
                    run.recorded_bytes += len(value.encode()) if value is not None else 0
                    session.add(
                        RecordedValue(
                            run_id=run_id,
                            step_id=step_id,
                            name=name,
                            availability=item["availability"],
                            value=value,
                        )
                    )
            self._event(
                session,
                run,
                "attempt_finished",
                step_id,
                number,
                {
                    "state": outcome.state,
                    "code": outcome.code,
                    "status_code": outcome.status_code,
                    "duration": duration,
                    "retryable": outcome.retryable,
                    "retry_delay": retry_delay,
                },
            )

    def skip(self, run_id: str, step_id: str, causes: list[str]) -> None:
        with self._session() as session, session.begin():
            run = self._run(session, run_id)
            step = session.get(StepRun, (run_id, step_id))
            if step is None or step.state != State.PENDING:
                raise ForgeFlowError(ErrorCode.STORAGE)
            step.state, step.causes = State.SKIPPED, encoded(causes)
            self._event(session, run, "step_skipped", step_id, payload={"causes": list(causes)})

    def finish_run(self, run_id: str, state: State) -> None:
        with self._session() as session, session.begin():
            run = self._run(session, run_id)
            run.state, run.ended = state, now()
            for step in session.scalars(select(StepRun).where(StepRun.run_id == run_id)):
                if State(step.state) not in TERMINAL:
                    step.state = (
                        State.INTERRUPTED if state == State.INTERRUPTED else State.CANCELLED
                    )
            for attempt in session.scalars(
                select(Attempt).where(Attempt.run_id == run_id, Attempt.state == State.RUNNING)
            ):
                attempt.state = State.INTERRUPTED if state == State.INTERRUPTED else State.CANCELLED
            self._event(session, run, "run_finished", payload={"state": state})

    def history(self) -> list[dict[str, JsonValue]]:
        with Session(self.engine) as session:
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "parent_id": row.parent_id,
                    "mode": row.mode,
                    "state": row.state,
                    "created": row.created,
                    "ended": row.ended,
                }
                for row in session.scalars(select(Run).order_by(Run.created.desc()).limit(100))
            ]

    def snapshot(self, run_id: str) -> Snapshot:
        with Session(self.engine) as session:
            run = self._run(session, run_id)
            steps = list(
                session.scalars(
                    select(StepRun).where(StepRun.run_id == run_id).order_by(StepRun.position)
                )
            )
            attempts = tuple(
                AttemptData(
                    row.step_id,
                    row.number,
                    State(row.state),
                    ErrorCode(row.code) if row.code else None,
                    row.status_code,
                    row.duration or 0,
                    row.retryable,
                    row.retry_delay,
                )
                for row in session.scalars(
                    select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.id)
                )
            )
            values: dict[str, dict[str, dict[str, JsonValue]]] = {}
            for row in session.scalars(select(RecordedValue).where(RecordedValue.run_id == run_id)):
                item: dict[str, JsonValue] = {"availability": row.availability}
                if row.availability == "present":
                    item["value"] = json.loads(row.value or "null")
                values.setdefault(row.step_id, {})[row.name] = item
            events = tuple(
                EventData(row.sequence, row.kind, row.step_id, row.attempt, json.loads(row.payload))
                for row in session.scalars(
                    select(Event).where(Event.run_id == run_id).order_by(Event.sequence)
                )
            )
            return Snapshot(
                run.id,
                run.name,
                run.parent_id,
                run.mode,
                State(run.state),
                json.loads(run.plan),
                {row.step_id: State(row.state) for row in steps},
                {row.step_id: cast(list[str], json.loads(row.causes)) for row in steps},
                attempts,
                values,
                events,
            )

    def recover(self) -> list[str]:
        with Session(self.engine) as session:
            ids = list(session.scalars(select(Run.id).where(Run.state.in_(["PENDING", "RUNNING"]))))
        for run_id in ids:
            self.finish_run(run_id, State.INTERRUPTED)
        return ids

    def prune(self, older_than_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        with self._session() as session, session.begin():
            ids = list(
                session.scalars(
                    select(Run.id).where(Run.created < cutoff, Run.state.in_(list(TERMINAL)))
                )
            )
            session.execute(delete(Run).where(Run.id.in_(ids)))
            return len(ids)


class StorageWorker:
    """Serialize session ownership in one thread; cancellation never abandons a queued write."""

    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forgeflow-storage")

    async def call[T](self, operation: Callable[[], T]) -> T:
        future = asyncio.get_running_loop().run_in_executor(self.executor, operation)
        return await asyncio.shield(future)

    async def close(self) -> None:
        await asyncio.to_thread(self.executor.shutdown, wait=True)
