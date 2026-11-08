"""HTTP GET/HEAD adapter with isolated clients and no raw request/response persistence."""

import logging
import os
import ssl
from collections.abc import Callable
from contextvars import ContextVar

import httpx
from pydantic import JsonValue

from forgeflow.domain import ErrorCode, ForgeFlowError, Outcome, State
from forgeflow.engine.http_data import MAX_RESPONSE_BYTES, json_pointer, parse_response
from forgeflow.engine.pure import execute_pure, resolve
from forgeflow.engine.retry import parse_retry_after
from forgeflow.recorder.privacy import MAX_CAPTURE_BYTES, Privacy, encoded
from forgeflow.workflow.graph import WorkflowStep
from forgeflow.workflow.models import HeaderSecret, HttpStep, Workflow

_IN_REQUEST: ContextVar[bool] = ContextVar("forgeflow_http_request", default=False)


class _TransportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _IN_REQUEST.get()


_LOG_FILTER = _TransportLogFilter()


def _filter_transport_logs() -> None:
    # HTTPX logs full URLs at INFO; httpcore DEBUG traces can contain request data.
    for name in tuple(logging.Logger.manager.loggerDict):
        if name == "httpx" or name.startswith("httpcore"):
            logging.getLogger(name).addFilter(_LOG_FILTER)


def _tls_failure(error: BaseException) -> bool:
    visited: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in visited:
        if isinstance(current, ssl.SSLError):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


class HttpHandler:
    """Prepare secrets once before dispatch. Construct network transports only for HTTP steps."""

    def __init__(
        self,
        workflow: Workflow,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self.transport_factory = transport_factory
        self.headers: dict[str, dict[str, str]] = {}
        secrets: list[str] = []
        for step in workflow.steps:
            if not isinstance(step, HttpStep):
                continue
            headers: dict[str, str] = {"Accept-Encoding": "identity"}
            for name, operand in step.request.headers.items():
                if isinstance(operand, HeaderSecret):
                    value = os.environ.get(operand.secret)
                    if not value:
                        raise ForgeFlowError(ErrorCode.SECRET_MISSING)
                    complete = operand.prefix + value
                    if len(complete) > 8192 or any(
                        ord(char) < 32 or ord(char) > 126 for char in complete
                    ):
                        raise ForgeFlowError(ErrorCode.SECRET_HEADER_INVALID)
                    headers[name] = complete
                    secrets.extend((value, complete))
                else:
                    headers[name] = operand.literal
            self.headers[step.id] = headers
        self.privacy = Privacy(tuple(dict.fromkeys(secrets)))

    async def __call__(
        self, step: WorkflowStep, outputs: dict[str, dict[str, JsonValue]]
    ) -> Outcome:
        if not isinstance(step, HttpStep):
            return execute_pure(step, outputs)
        query: dict[str, str] = {}
        for name, operand in step.request.query.items():
            value = resolve(operand, outputs)
            if value is None or isinstance(value, (dict, list)):
                return Outcome(State.FAILED, code=ErrorCode.QUERY_SCALAR_REQUIRED)
            query[name] = value if isinstance(value, str) else encoded(value)
        token = _IN_REQUEST.set(True)
        try:
            transport = (
                self.transport_factory()
                if self.transport_factory
                else httpx.AsyncHTTPTransport(retries=0, verify=True, trust_env=False)
            )
            _filter_transport_logs()
            phase_timeout = min(step.attempt_timeout_seconds or 30, 10)
            async with httpx.AsyncClient(
                transport=transport, trust_env=False, follow_redirects=False, timeout=phase_timeout
            ) as client:
                async with client.stream(
                    step.request.method,
                    step.request.url,
                    params=query,
                    headers=self.headers[step.id],
                ) as response:
                    return await self._response(step, response)
        except httpx.TimeoutException:
            return Outcome(State.TIMED_OUT, code=ErrorCode.TIMEOUT, retryable=True)
        except httpx.ConnectError as error:
            code = ErrorCode.HTTP_TLS if _tls_failure(error) else ErrorCode.HTTP_CONNECTION
            return Outcome(State.FAILED, code=code, retryable=code != ErrorCode.HTTP_TLS)
        except (httpx.ReadError, httpx.WriteError):
            return Outcome(State.FAILED, code=ErrorCode.HTTP_READ, retryable=True)
        except httpx.HTTPError:
            return Outcome(State.FAILED, code=ErrorCode.HTTP_PROTOCOL)
        finally:
            _IN_REQUEST.reset(token)

    @staticmethod
    async def _response(step: HttpStep, response: httpx.Response) -> Outcome:
        status = response.status_code
        if status not in step.expect_status:
            return Outcome(
                State.FAILED,
                code=ErrorCode.HTTP_STATUS,
                status_code=status,
                retryable=status in {408, 429, 502, 503, 504},
                retry_after=parse_retry_after(response.headers.get("Retry-After"))
                if status in {408, 429, 502, 503, 504}
                else None,
            )
        captured: dict[str, JsonValue] = {"status_code": status}
        try:
            if step.capture:
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if encoding != "identity":
                    raise ForgeFlowError(ErrorCode.HTTP_ENCODING)
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type != "application/json" and not (
                    content_type.startswith("application/") and content_type.endswith("+json")
                ):
                    raise ForgeFlowError(ErrorCode.HTTP_JSON)
                if response.is_stream_consumed:
                    body = response.content
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ForgeFlowError(ErrorCode.HTTP_SIZE)
                else:
                    buffer = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(buffer) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ForgeFlowError(ErrorCode.HTTP_SIZE)
                        buffer.extend(chunk)
                    body = bytes(buffer)
                document = parse_response(body)
                for name, pointer in step.capture.items():
                    captured[name] = json_pointer(document, pointer)
                if len(encoded(captured).encode()) > MAX_CAPTURE_BYTES:
                    raise ForgeFlowError(ErrorCode.CAPTURE_SIZE)
            return Outcome(State.SUCCEEDED, captured, status_code=status)
        except ForgeFlowError as error:
            return Outcome(State.FAILED, code=error.code, status_code=status)
