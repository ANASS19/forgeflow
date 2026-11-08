"""Real HTTP GET/HEAD through the CLI against a loopback-only fixture API."""

import json
import logging
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from forgeflow.cli import app
from forgeflow.engine.http import HttpHandler
from forgeflow.storage.repository import Repository
from forgeflow.workflow import parse_workflow
from forgeflow.workflow.models import HttpStep


@pytest.fixture
def local_api() -> Iterator[tuple[str, list[str]]]:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append("GET " + self.path)
            body = json.dumps(
                {"status": "ok", "value": 7, "uncaptured": "SYNTHETIC_BODY_ONLY"}
            ).encode()
            if self.path == "/transient":
                status = 503 if requests.count("GET /transient") == 1 else 200
            else:
                status = 200 if self.path.startswith("/health") else 404
            self.send_response(status)
            if status == 503:
                self.send_header("Retry-After", "0")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self) -> None:
            requests.append("HEAD " + self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_get_head_and_captured_dependency_through_cli(
    tmp_path: Path,
    local_api: tuple[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url, requests = local_api
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://invalid.example.test:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("SSL_CERT_FILE", "nonexistent-certificate-file")
    caplog.set_level(logging.DEBUG)
    source = tmp_path / "workflow.yaml"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "loopback",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {
                            "method": "GET",
                            "url": url + "/health",
                            "query": {"enabled": {"literal": False}},
                        },
                        "capture": {"state": "/status"},
                    },
                    {
                        "id": "probe",
                        "type": "http",
                        "needs": ["fetch"],
                        "request": {"method": "HEAD", "url": url + "/health"},
                    },
                    {
                        "id": "check",
                        "type": "assert",
                        "needs": ["fetch", "probe"],
                        "left": {"ref": "fetch.outputs.state"},
                        "op": "eq",
                        "right": {"literal": "ok"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    directory = tmp_path / "data"
    result = CliRunner().invoke(app, ["run", str(source), "--data-dir", str(directory), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["state"] == "SUCCEEDED"
    assert requests == ["GET /health?enabled=false", "HEAD /health"]
    with Repository(directory) as repository:
        snapshot = repository.snapshot(payload["id"])
        assert len(snapshot.attempts) == 3
        assert snapshot.values["fetch"]["state"] == {"availability": "present", "value": "ok"}
    assert "127.0.0.1" not in caplog.text
    assert all(
        b"SYNTHETIC_BODY_ONLY" not in path.read_bytes()
        for path in directory.glob("history.sqlite3*")
    )


def test_http_failure_is_persisted_and_blocks_dependants(
    tmp_path: Path,
    local_api: tuple[str, list[str]],
) -> None:
    url, _ = local_api
    source = tmp_path / "workflow.yaml"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "failed-http",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {"method": "GET", "url": url + "/missing"},
                    },
                    {"id": "blocked", "type": "value", "needs": ["fetch"], "values": {"x": 1}},
                ],
            }
        ),
        encoding="utf-8",
    )
    directory = tmp_path / "data"
    result = CliRunner().invoke(app, ["run", str(source), "--data-dir", str(directory), "--json"])
    payload = json.loads(result.output)
    assert result.exit_code == 1 and payload["steps"]["blocked"] == "SKIPPED"
    with Repository(directory) as repository:
        attempt = repository.snapshot(payload["id"]).attempts[0]
        assert attempt.code == "HTTP_STATUS_UNEXPECTED" and attempt.status_code == 404


@pytest.mark.asyncio
async def test_cookies_are_not_shared_between_attempts() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "cookie" not in request.headers
        return httpx.Response(200, headers={"Set-Cookie": "session=SYNTHETIC_COOKIE; Path=/"})

    source = parse_workflow(
        json.dumps(
            {
                "schema_version": 1,
                "name": "cookies",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {"method": "GET", "url": "https://example.test"},
                    },
                ],
            }
        ).encode()
    )
    handler = HttpHandler(source, transport_factory=lambda: httpx.MockTransport(respond))
    step = source.steps[0]
    assert isinstance(step, HttpStep)
    await handler(step, {})
    await handler(step, {})
    assert len(requests) == 2


def test_cli_retries_a_temporary_loopback_failure(
    tmp_path: Path,
    local_api: tuple[str, list[str]],
) -> None:
    url, requests = local_api
    source = tmp_path / "workflow.yaml"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "local-retry",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "retry": {"max_attempts": 3},
                        "request": {"method": "GET", "url": url + "/transient"},
                        "capture": {"value": "/value"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    directory = tmp_path / "data"
    result = CliRunner().invoke(app, ["run", str(source), "--data-dir", str(directory), "--json"])
    assert result.exit_code == 0, result.output
    with Repository(directory) as repository:
        attempts = repository.snapshot(json.loads(result.output)["id"]).attempts
    assert requests == ["GET /transient", "GET /transient"]
    assert [item.status_code for item in attempts] == [503, 200]
    assert attempts[0].retry_delay is not None and 0 <= attempts[0].retry_delay <= 0.5
