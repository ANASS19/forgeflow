"""Schema-v1 structural constraints without graph or execution behavior."""

import json

import pytest
from pydantic import ValidationError

from forgeflow.workflow import DiagnosticCode as Code
from forgeflow.workflow import Workflow, WorkflowLoadError, parse_workflow
from forgeflow.workflow.models import AssertStep, HttpStep, ValueStep


def _step(**changes: object) -> dict[str, object]:
    return {"id": "seed", "type": "value", "values": {"count": 1}, **changes}


def _request(**changes: object) -> dict[str, object]:
    return {"method": "GET", "url": "https://api.example.test/health", **changes}


def _http(**changes: object) -> dict[str, object]:
    return {"id": "fetch", "type": "http", "request": _request(), **changes}


def _document(step: dict[str, object] | None = None, **changes: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "api-health",
        "steps": [step if step is not None else _step()],
        **changes,
    }


def _load(document: dict[str, object]) -> Workflow:
    return parse_workflow(json.dumps(document).encode())


def _invalid(document: dict[str, object], code: Code | None = None) -> WorkflowLoadError:
    with pytest.raises(WorkflowLoadError) as caught:
        _load(document)
    if code is not None:
        assert code in {item.code for item in caught.value.diagnostics}
    return caught.value


def test_typed_steps_and_default_configuration() -> None:
    workflow = _load(
        _document(
            steps=[
                _step(),
                _http(),
                {
                    "id": "check",
                    "type": "assert",
                    "left": {"literal": 1},
                    "op": "eq",
                    "right": {"ref": "seed.outputs.count"},
                },
            ]
        )
    )
    assert isinstance(workflow.steps[0], ValueStep)
    assert isinstance(workflow.steps[1], HttpStep)
    assert isinstance(workflow.steps[2], AssertStep)
    assert workflow.execution.concurrency == 4
    assert workflow.execution.timeout_seconds == 300
    assert workflow.defaults.attempt_timeout_seconds == 30
    assert workflow.steps[0].attempt_timeout_seconds is None
    assert workflow.steps[1].retry.max_attempts == 1
    assert workflow.steps[1].expect_status == list(range(200, 300))


def test_explicit_configuration_and_query_references() -> None:
    workflow = _load(
        _document(
            _http(
                attempt_timeout_seconds=300,
                request=_request(
                    query={"limit": {"literal": 100}, "id": {"ref": "seed.outputs.count"}},
                    headers={"Authorization": {"secret": "EXAMPLE_TOKEN", "prefix": "Bearer "}},
                ),
                retry={"max_attempts": 5},
                expect_status=[200, 204],
                capture={"state": "/status"},
            ),
            execution={"concurrency": 16, "timeout_seconds": 3600},
            defaults={"attempt_timeout_seconds": 0.5},
        )
    )
    step = workflow.steps[0]
    assert isinstance(step, HttpStep)
    assert step.attempt_timeout_seconds == 300
    assert step.retry.max_attempts == 5
    assert step.request.query["id"].model_dump() == {"ref": "seed.outputs.count"}


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 0, 2, None])
def test_schema_version_is_exact_integer_one(version: object) -> None:
    _invalid(_document(schema_version=version), Code.VERSION)


@pytest.mark.parametrize("field", ["schema_version", "name", "steps"])
def test_required_workflow_fields(field: str) -> None:
    document = _document()
    del document[field]
    error = _invalid(document, Code.REQUIRED)
    assert error.diagnostics[0].location == (field,)


@pytest.mark.parametrize("field", ["id", "type", "values"])
def test_required_step_fields(field: str) -> None:
    step = _step()
    del step[field]
    _invalid(_document(step), Code.REQUIRED)


@pytest.mark.parametrize("field", ["method", "url"])
def test_required_request_fields(field: str) -> None:
    request = _request()
    del request[field]
    _invalid(_document(_http(request=request)), Code.REQUIRED)


@pytest.mark.parametrize("kind", ["shell", "python", "HTTP", "", 42, None])
def test_unsupported_step_types(kind: object) -> None:
    _invalid(_document(_step(type=kind)), Code.STEP_TYPE)


@pytest.mark.parametrize(
    "identifier", ["", "Upper", "has-dash", "a.b", "9start", "a" * 65, 1, "seed\n"]
)
def test_invalid_identifiers(identifier: object) -> None:
    _invalid(_document(_step(id=identifier)))


@pytest.mark.parametrize(
    "document",
    [
        _document(name=True),
        _document(steps={}),
        _document(steps=[]),
        _document(execution=None),
        _document(defaults=[]),
        _document(_step(needs="seed")),
        _document(_step(values=[])),
        _document(_step(values={})),
        _document(_step(values={"invalid-key": 1})),
        _document(_step(needs=[True])),
        _document(_step(attempt_timeout_seconds=None)),
    ],
)
def test_invalid_field_types_and_shapes(document: dict[str, object]) -> None:
    _invalid(document)


@pytest.mark.parametrize(
    "document",
    [
        _document(unknown=1),
        _document(_step(unknown=1)),
        _document(execution={"unknown": 1}),
        _document(defaults={"unknown": 1}),
        _document(_http(request=_request(body={}))),
        _document(_http(retry={"unknown": 1})),
        _document(_step(retry={"max_attempts": 2})),
    ],
)
def test_unknown_fields_rejected_at_each_level(document: dict[str, object]) -> None:
    _invalid(document, Code.UNKNOWN)


@pytest.mark.parametrize("value", [0, 17, True, "4", 4.0])
def test_concurrency_bounds_and_types(value: object) -> None:
    _invalid(_document(execution={"concurrency": value}))


@pytest.mark.parametrize("value", [0, 3601, True, "300"])
def test_workflow_timeout_bounds_and_types(value: object) -> None:
    _invalid(_document(execution={"timeout_seconds": value}))


@pytest.mark.parametrize("value", [0, 301, True, "30"])
def test_attempt_timeout_bounds_and_types(value: object) -> None:
    _invalid(_document(defaults={"attempt_timeout_seconds": value}))
    _invalid(_document(_step(attempt_timeout_seconds=value)))


@pytest.mark.parametrize("value", [0, 6, True, "3", 2.0])
def test_retry_bounds_and_types(value: object) -> None:
    _invalid(_document(_http(retry={"max_attempts": value})))


def test_duplicate_step_ids_and_needs() -> None:
    _invalid(_document(steps=[_step(), _step()]), Code.STEP_DUPLICATE)
    _invalid(_document(_step(needs=["other", "other"])), Code.NEEDS_DUPLICATE)


def test_step_count_boundary() -> None:
    steps = [_step(id=f"s{i}") for i in range(100)]
    assert len(_load(_document(steps=steps)).steps) == 100
    _invalid(_document(steps=steps + [_step(id="extra")]), Code.BOUNDS)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "get", True])
def test_http_method_restrictions(method: object) -> None:
    _invalid(_document(_http(request=_request(method=method))), Code.VALUE)


@pytest.mark.parametrize("body_field", ["body", "json", "data", "content", "files"])
def test_http_bodies_forbidden(body_field: str) -> None:
    _invalid(_document(_http(request=_request(**{body_field: "synthetic"}))), Code.UNKNOWN)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/data",
        "ftp://example.test",
        "relative/path",
        "https://",
        "https://user:password@example.test",
        "https://example.test/?token=synthetic",
        "https://example.test/#fragment",
        "https://example.test/?",
        "https://example.test/#",
        "https://example.test:99999",
        "https://example.test:0",
        "https://example.test:invalid",
        "https://example.test/\r\ninjected",
        "https://exa mple.test",
        "https://exa<mple.test",
        "https://example.test\\other",
        "https://%65xample.test",
        "http://[invalid]/",
    ],
)
def test_url_structure(url: str) -> None:
    _invalid(_document(_http(request=_request(url=url))), Code.URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/health",
        "https://api.example.test",
        "http://127.0.0.1:8000/",
        "http://[::1]:8000/",
        "https://example.test./health",
        "https://例え.test/health",
    ],
)
def test_local_and_international_endpoints_allowed(url: str) -> None:
    assert isinstance(_load(_document(_http(request=_request(url=url)))).steps[0], HttpStep)


@pytest.mark.parametrize(
    "headers",
    [
        {"Bad\r\nHeader": {"literal": "value"}},
        {"X-Test": {"literal": "a\rb"}},
        {"X-Test": {"literal": "a\nb"}},
        {"X-Test": {"literal": "a\x00b"}},
        {"Bad Header": {"literal": "value"}},
        {"": {"literal": "value"}},
        {"Accept": {"literal": "a"}, "accept": {"literal": "b"}},
        {"Host": {"literal": "example.test"}},
        {"Content-Length": {"literal": "1"}},
        {"Transfer-Encoding": {"literal": "chunked"}},
        {"Cookie": {"literal": "synthetic"}},
        {"Connection": {"literal": "close"}},
        {"Accept-Encoding": {"literal": "gzip"}},
        {"X-Test": {"secret": "EXAMPLE_SECRET", "prefix": "Bearer\n"}},
    ],
)
def test_dangerous_headers(headers: dict[str, object]) -> None:
    _invalid(_document(_http(request=_request(headers=headers))), Code.HEADER)


@pytest.mark.parametrize("header", ["Authorization", "authorization", "X-API-Key", "X-Auth-Token"])
def test_credential_headers_require_secret_operands(header: str) -> None:
    _invalid(
        _document(_http(request=_request(headers={header: {"literal": "synthetic"}}))),
        Code.HEADER_SECRET,
    )
    assert _load(_document(_http(request=_request(headers={header: {"secret": "EXAMPLE_SECRET"}}))))


@pytest.mark.parametrize(
    "operand",
    [
        {},
        {"secret": "bad-name"},
        {"literal": 1},
        {"ref": "seed.outputs.count"},
        {"literal": "x", "secret": "EXAMPLE_SECRET"},
    ],
)
def test_malformed_header_operands(operand: dict[str, object]) -> None:
    _invalid(_document(_http(request=_request(headers={"X-Test": operand}))))


@pytest.mark.parametrize("key", ["token", "api-key", "ACCESS_TOKEN", "password", "bad\nkey", ""])
def test_credential_or_dangerous_query_keys(key: str) -> None:
    _invalid(_document(_http(request=_request(query={key: {"literal": "synthetic"}}))), Code.QUERY)


@pytest.mark.parametrize("value", [None, [], {}, {"x": 1}])
def test_query_literals_must_be_non_null_scalars(value: object) -> None:
    _invalid(_document(_http(request=_request(query={"filter": {"literal": value}}))))


@pytest.mark.parametrize(
    "capture",
    [
        {"data": ""},
        {"data": "relative"},
        {"data": "/invalid~"},
        {"data": "/invalid~2"},
        {"status_code": "/status"},
        {"data": 1},
        {"bad-key": "/status"},
    ],
)
def test_invalid_captures(capture: dict[str, object]) -> None:
    _invalid(_document(_http(capture=capture)))


def test_json_pointer_escaping_and_head_capture_rule() -> None:
    assert _load(_document(_http(capture={"data": "/a~1b/~0key", "empty_key": "/"})))
    _invalid(
        _document(_http(request=_request(method="HEAD"), capture={"data": "/data"})),
        Code.HEAD_CAPTURE,
    )
    assert _load(_document(_http(request=_request(method="HEAD"), capture={})))


@pytest.mark.parametrize("statuses", [[], [99], [600], [True], ["200"], 200])
def test_expected_status_constraints(statuses: object) -> None:
    _invalid(_document(_http(expect_status=statuses)))


@pytest.mark.parametrize(
    "operand",
    [
        {},
        {"literal": 1, "ref": "seed.outputs.count"},
        {"ref": "bad"},
        {"ref": 1},
        {"unknown": 1},
        {"literal": 1, "unknown": 2},
    ],
)
def test_malformed_assert_operands(operand: dict[str, object]) -> None:
    _invalid(
        _document(
            {"id": "check", "type": "assert", "left": operand, "op": "eq", "right": {"literal": 1}}
        )
    )


@pytest.mark.parametrize("field", ["left", "op", "right"])
def test_required_assert_fields(field: str) -> None:
    step: dict[str, object] = {
        "id": "check",
        "type": "assert",
        "left": {"literal": 1},
        "op": "eq",
        "right": {"literal": 1},
    }
    del step[field]
    _invalid(_document(step), Code.REQUIRED)


def test_graph_and_reference_targets_are_deferred() -> None:
    workflow = _load(
        _document(
            steps=[
                _step(needs=["check", "unknown"]),
                {
                    "id": "check",
                    "type": "assert",
                    "needs": ["seed"],
                    "left": {"ref": "unknown.outputs.missing"},
                    "op": "eq",
                    "right": {"literal": 1},
                },
            ]
        )
    )
    assert len(workflow.steps) == 2  # Cycles and missing targets belong to Session 3.


def test_direct_models_reject_nonfinite_json() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            Workflow.model_validate(_document(_step(values={"nested": [value]})))
