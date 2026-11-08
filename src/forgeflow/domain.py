"""Execution states and safe failure codes shared by adapters and the engine."""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import JsonValue


class State(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL = frozenset(
    {
        State.SUCCEEDED,
        State.FAILED,
        State.TIMED_OUT,
        State.SKIPPED,
        State.CANCELLED,
        State.INTERRUPTED,
    }
)


class ErrorCode(StrEnum):
    ASSERTION_FAILED = "ASSERTION_FAILED"
    OUTPUT_UNAVAILABLE = "OUTPUT_UNAVAILABLE"
    QUERY_SCALAR_REQUIRED = "QUERY_SCALAR_REQUIRED"
    SECRET_MISSING = "SECRET_MISSING"
    SECRET_HEADER_INVALID = "SECRET_HEADER_INVALID"
    HTTP_STATUS = "HTTP_STATUS_UNEXPECTED"
    HTTP_CONNECTION = "HTTP_CONNECTION_FAILED"
    HTTP_READ = "HTTP_READ_FAILED"
    HTTP_TLS = "HTTP_TLS_FAILED"
    HTTP_PROTOCOL = "HTTP_PROTOCOL_FAILED"
    HTTP_ENCODING = "HTTP_ENCODING_UNSUPPORTED"
    HTTP_SIZE = "HTTP_RESPONSE_TOO_LARGE"
    HTTP_JSON = "HTTP_JSON_INVALID"
    CAPTURE_MISSING = "HTTP_CAPTURE_MISSING"
    CAPTURE_SIZE = "HTTP_CAPTURE_TOO_LARGE"
    TIMEOUT = "ATTEMPT_TIMED_OUT"
    INTERNAL = "INTERNAL_ERROR"
    STORAGE = "STORAGE_ERROR"
    STORAGE_LIMIT = "RECORDING_LIMIT_EXCEEDED"
    SCHEMA = "DATABASE_VERSION_UNSUPPORTED"
    BUSY = "WRITER_BUSY"
    NOT_FOUND = "RUN_NOT_FOUND"
    PARENT = "PARENT_RUN_NOT_TERMINAL"
    RECOVERY = "RECOVERY_REQUIRED"
    REPLAY_INCOMPLETE = "REPLAY_RECORDING_INCOMPLETE"
    REPLAY_VALUE = "REPLAY_VALUE_UNAVAILABLE"
    REPLAY_VERSION = "REPLAY_VERSION_UNSUPPORTED"
    REPLAY_DIVERGENCE = "REPLAY_DIVERGENCE"


class ForgeFlowError(Exception):
    """Never carries raw third-party exceptions or user input."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class Outcome:
    state: State
    outputs: dict[str, JsonValue] = field(default_factory=dict)
    code: ErrorCode | None = None
    retryable: bool = False
    status_code: int | None = None
    retry_after: float | None = None


@dataclass(frozen=True)
class RunResult:
    id: str
    state: State
    steps: dict[str, State]


def exit_code(state: State) -> int:
    return {State.SUCCEEDED: 0, State.TIMED_OUT: 124, State.CANCELLED: 130}.get(state, 1)
