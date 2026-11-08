"""Focused HTTP adapter contracts with no public services or real credentials."""

import asyncio
import json
import logging
import ssl
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from forgeflow.domain import ErrorCode as Code
from forgeflow.domain import ForgeFlowError, State
from forgeflow.engine.http import HttpHandler
from forgeflow.engine.http_data import MAX_RESPONSE_BYTES, json_pointer, parse_response
from forgeflow.engine.runner import execute
from forgeflow.storage.repository import Repository
from forgeflow.workflow import parse_workflow
from forgeflow.workflow.models import HttpStep, Workflow


def workflow(
    *,
    request: dict[str, object] | None = None,
    capture: dict[str, str] | None = None,
    **changes: object,
) -> Workflow:
    return parse_workflow(
        json.dumps(
            {
                "schema_version": 1,
                "name": "http-test",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {
                            "method": "GET",
                            "url": "https://api.example.test/health",
                            **(request or {}),
                        },
                        "capture": {"value": "/value"} if capture is None else capture,
                        **changes,
                    }
                ],
            }
        ).encode()
    )


def step(source: Workflow) -> HttpStep:
    result = source.steps[0]
    assert isinstance(result, HttpStep)
    return result


@pytest.mark.asyncio
async def test_get_resolves_query_and_explicit_captures() -> None:
    source = workflow(
        request={"query": {"enabled": {"literal": False}, "id": {"ref": "seed.outputs.id"}}},
        capture={"item": "/a~1b/~0key/1", "empty": "/empty"},
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert dict(request.url.params) == {"enabled": "false", "id": "7"}
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200, json={"a/b": {"~key": [1, 2]}, "empty": None, "uncaptured": "NOT_RETAINED"}
        )

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    result = await handler(step(source), {"seed": {"id": 7}})
    assert result.state == State.SUCCEEDED
    assert result.outputs == {"status_code": 200, "item": 2, "empty": None}


@pytest.mark.asyncio
async def test_head_does_not_read_a_body() -> None:
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise AssertionError("HEAD body must not be read.")
            yield b""  # pragma: no cover

    source = workflow(request={"method": "HEAD"}, capture={})
    handler = HttpHandler(
        source,
        transport_factory=lambda: httpx.MockTransport(
            lambda request: httpx.Response(204, stream=Unreadable())
        ),
    )
    result = await handler(step(source), {})
    assert result.outputs == {"status_code": 204}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retryable", [(302, False), (404, False), (429, True), (503, True)])
async def test_unexpected_status_does_not_follow_redirects_or_retry(
    status: int, retryable: bool
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://private.example.test/"})

    source = workflow(capture={})
    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    result = await handler(step(source), {})
    assert result.code == Code.HTTP_STATUS and result.status_code == status
    assert result.retryable is retryable
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_explicitly_accepted_error_status_is_success() -> None:
    source = workflow(capture={}, expect_status=[503])
    handler = HttpHandler(
        source, transport_factory=lambda: httpx.MockTransport(lambda request: httpx.Response(503))
    )
    assert (await handler(step(source), {})).state == State.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,headers,code",
    [
        (b"not json", {"content-type": "application/json"}, Code.HTTP_JSON),
        (b'{"value": 1}', {"content-type": "text/plain"}, Code.HTTP_JSON),
        (
            b'{"value": 1}',
            {"content-type": "application/json", "content-encoding": "gzip"},
            Code.HTTP_ENCODING,
        ),
        (b'{"other": 1}', {"content-type": "application/json"}, Code.CAPTURE_MISSING),
        (b'{"value": 1, "value": 2}', {"content-type": "application/json"}, Code.HTTP_JSON),
        (b'{"value": NaN}', {"content-type": "application/json"}, Code.HTTP_JSON),
        (b'{"value": 1e9999}', {"content-type": "application/json"}, Code.HTTP_JSON),
        (
            b'{"value": "' + b"x" * (256 * 1024) + b'"}',
            {"content-type": "application/json"},
            Code.CAPTURE_SIZE,
        ),
    ],
)
async def test_invalid_responses_are_sanitized(
    body: bytes, headers: dict[str, str], code: Code
) -> None:
    source = workflow()
    handler = HttpHandler(
        source,
        transport_factory=lambda: httpx.MockTransport(
            lambda request: httpx.Response(200, stream=httpx.ByteStream(body), headers=headers)
        ),
    )
    result = await handler(step(source), {})
    assert result.code == code and result.status_code == 200
    assert result.outputs == {}


@pytest.mark.asyncio
async def test_stream_limit_stops_reading_and_closes_response() -> None:
    read = 0
    closed = False

    class LargeBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal read
            for _ in range(5):
                read += 1
                yield b"x" * (MAX_RESPONSE_BYTES // 2)

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    source = workflow()
    handler = HttpHandler(
        source,
        transport_factory=lambda: httpx.MockTransport(
            lambda request: httpx.Response(
                200, stream=LargeBody(), headers={"content-type": "application/json"}
            )
        ),
    )
    result = await handler(step(source), {})
    assert result.code == Code.HTTP_SIZE
    assert read == 3 and closed


@pytest.mark.parametrize(
    "body", [b"[" * 33 + b"0" + b"]" * 33, b'{"x":' + b"1" * 4097 + b"}", b'"\xff"']
)
def test_json_parser_budgets(body: bytes) -> None:
    with pytest.raises(ForgeFlowError) as error:
        parse_response(body)
    assert error.value.code == Code.HTTP_JSON


def test_json_string_brackets_do_not_count_as_depth() -> None:
    assert parse_response(json.dumps({"x": "[" * 40 + '\\"'}).encode()) == {"x": "[" * 40 + '\\"'}
    with pytest.raises(ForgeFlowError):
        json_pointer([1], "/01")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code",
    [
        ("connection", Code.HTTP_CONNECTION),
        ("tls", Code.HTTP_TLS),
        ("read", Code.HTTP_READ),
        ("timeout", Code.TIMEOUT),
        ("protocol", Code.HTTP_PROTOCOL),
    ],
)
async def test_transport_failure_codes(kind: str, code: Code) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        if kind == "tls":
            raise httpx.ConnectError("SYNTHETIC_PRIVATE_ERROR") from ssl.SSLCertVerificationError()
        errors = {
            "connection": httpx.ConnectError,
            "read": httpx.ReadError,
            "timeout": httpx.ReadTimeout,
            "protocol": httpx.RemoteProtocolError,
        }
        raise errors[kind]("SYNTHETIC_PRIVATE_ERROR")

    source = workflow()
    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(fail))
    result = await handler(step(source), {})
    assert result.code == code
    assert "SYNTHETIC_PRIVATE_ERROR" not in repr(result)


@pytest.mark.parametrize(
    "value,code",
    [
        (None, Code.SECRET_MISSING),
        ("", Code.SECRET_MISSING),
        ("bad\r\nvalue", Code.SECRET_HEADER_INVALID),
        ("nonascii_世界", Code.SECRET_HEADER_INVALID),
    ],
)
def test_secret_preflight(value: str | None, code: Code, monkeypatch: pytest.MonkeyPatch) -> None:
    source = workflow(request={"headers": {"Authorization": {"secret": "TEST_SECRET"}}})
    if value is None:
        monkeypatch.delenv("TEST_SECRET", raising=False)
    else:
        monkeypatch.setenv("TEST_SECRET", value)
    with pytest.raises(ForgeFlowError) as error:
        HttpHandler(source)
    assert error.value.code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret,reflected",
    [
        ("SYNTHETIC_HEADER_SECRET", "SYNTHETIC_HEADER_SECRET"),
        ("123456789", 123456789),
    ],
)
async def test_secrets_and_request_data_do_not_reach_storage_or_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    secret: str,
    reflected: JsonValue,
) -> None:
    monkeypatch.setenv("TEST_SECRET", secret)
    caplog.set_level(logging.DEBUG)
    source = workflow(
        request={
            "headers": {"Authorization": {"secret": "TEST_SECRET", "prefix": "Bearer "}},
            "query": {"search": {"literal": "SYNTHETIC_QUERY_VALUE"}},
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer " + secret
        return httpx.Response(
            200,
            json={"value": reflected, "other": "SYNTHETIC_BODY_VALUE"},
            headers={"Set-Cookie": "SYNTHETIC_COOKIE"},
        )

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=handler)
        assert result.state == State.SUCCEEDED
        assert repository.snapshot(result.id).values["fetch"]["value"] == {
            "availability": "redacted"
        }
    for path in tmp_path.glob("history.sqlite3*"):
        data = path.read_bytes()
        assert all(
            value.encode() not in data
            for value in (
                secret,
                "api.example.test",
                "SYNTHETIC_QUERY_VALUE",
                "SYNTHETIC_BODY_VALUE",
                "SYNTHETIC_COOKIE",
            )
        )
    assert secret not in caplog.text and "api.example.test" not in caplog.text


@pytest.mark.asyncio
async def test_http_attempt_deadline_is_persisted(tmp_path: Path) -> None:
    source = workflow(attempt_timeout_seconds=0.01)

    async def delayed(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"value": 1})

    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(delayed))
    with Repository(tmp_path, writable=True) as repository:
        result = await execute(source, repository, handler=handler)
        snapshot = repository.snapshot(result.id)
        assert result.state == State.FAILED
        assert snapshot.attempts[0].state == State.TIMED_OUT
        assert snapshot.attempts[0].code == Code.TIMEOUT
