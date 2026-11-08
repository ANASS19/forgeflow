"""Ensure parser and validation failures cannot echo sensitive workflow data."""

import json
import traceback

import pytest

from forgeflow.workflow import DiagnosticCode as Code
from forgeflow.workflow import WorkflowLoadError, parse_workflow

CANARY = "SYNTHETIC_SECRET_CANARY_42"


@pytest.mark.parametrize(
    "source",
    [
        f'name: ["{CANARY}"',
        f"name: {CANARY}\nname: another",
        f"secret: &{CANARY} value",
        f"secret: *{CANARY}",
        f"secret: !{CANARY} value",
        json.dumps({"schema_version": 1, "name": CANARY, "steps": []}),
        json.dumps(
            {
                "schema_version": 1,
                "name": "safe",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {
                            "method": "GET",
                            "url": f"https://{CANARY}.example.test/?token={CANARY}",
                        },
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "name": "safe",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {
                            "method": "GET",
                            "url": "https://example.test",
                            "headers": {CANARY: {"literal": [CANARY]}},
                        },
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "name": "safe",
                "steps": [{"id": "seed", "type": "value", "values": {f"INVALID-{CANARY}": CANARY}}],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "name": "safe",
                CANARY: CANARY,
                "steps": [{"id": "seed", "type": "value", "values": {"count": 1}}],
            }
        ),
    ],
)
def test_sensitive_input_never_appears_in_diagnostics(
    source: str, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(source.encode())

    error = caught.value
    representations = [
        str(error),
        repr(error),
        repr(error.diagnostics),
        json.dumps([item.to_dict() for item in error.diagnostics]),
        "".join(traceback.format_exception(error)),
    ]
    assert error.__context__ is None or error.__suppress_context__
    for representation in representations:
        assert CANARY not in representation
        assert "https://" not in representation
        assert "input_value" not in representation
    captured = capsys.readouterr()
    assert captured.out == captured.err == caplog.text == ""


def test_machine_readable_schema_location() -> None:
    source = {
        "schema_version": 1,
        "name": "safe",
        "execution": {"concurrency": "4"},
        "steps": [{"id": "seed", "type": "value", "values": {"count": 1}}],
    }
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(json.dumps(source).encode())
    assert caught.value.diagnostics[0].to_dict() == {
        "code": "SCHEMA_TYPE_INVALID",
        "location": ["execution", "concurrency"],
        "message": "The field has an invalid type; implicit coercion is not supported.",
    }


def test_diagnostics_are_bounded_and_report_truncation() -> None:
    source = {
        "schema_version": 1,
        "name": "safe",
        "steps": [{"id": f"s{index}", "type": "value"} for index in range(100)],
    }
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(json.dumps(source).encode())
    diagnostics = caught.value.diagnostics
    assert len(diagnostics) == 51
    assert diagnostics[-1].code == Code.TRUNCATED
    assert diagnostics[0].location == ("steps", 0, "values")


def test_exactly_fifty_errors_do_not_claim_truncation() -> None:
    source = {
        "schema_version": 1,
        "name": "safe",
        "steps": [{"id": f"s{index}", "type": "value"} for index in range(50)],
    }
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(json.dumps(source).encode())
    assert len(caught.value.diagnostics) == 50
    assert all(item.code != Code.TRUNCATED for item in caught.value.diagnostics)
