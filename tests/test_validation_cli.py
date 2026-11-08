"""The validation CLI stays offline and emits versioned, sanitized results."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forgeflow.cli import app


def test_validate_and_doctor_examples() -> None:
    for command in ("validate", "doctor"):
        result = CliRunner().invoke(app, [command, "examples/values.yaml", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "valid"


def test_invalid_input_is_sanitized(tmp_path: Path) -> None:
    source = tmp_path / "workflow.yaml"
    source.write_text("name: [SYNTHETIC_CANARY", encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(source), "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["output_version"] == 1
    assert payload["diagnostics"][0]["code"] == "YAML_SYNTAX_INVALID"
    assert "SYNTHETIC_CANARY" not in result.output


def test_run_history_and_inspection(tmp_path: Path) -> None:
    runner = CliRunner()
    options = ["--data-dir", str(tmp_path), "--json"]
    result = runner.invoke(app, ["run", "examples/values.yaml", *options])
    assert result.exit_code == 0, result.output
    run_id = json.loads(result.output)["id"]
    history = runner.invoke(app, ["history", *options])
    assert json.loads(history.output)["runs"][0]["id"] == run_id
    inspected = runner.invoke(app, ["inspect", run_id, *options])
    assert json.loads(inspected.output)["state"] == "SUCCEEDED"


def test_empty_history_does_not_initialize_storage(tmp_path: Path) -> None:
    directory = tmp_path / "absent"
    result = CliRunner().invoke(app, ["history", "--data-dir", str(directory), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["runs"] == []
    assert not directory.exists()


def test_missing_http_secret_is_rejected_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "absent"
    source = tmp_path / "workflow.yaml"
    monkeypatch.delenv("FORGEFLOW_MISSING_TEST_SECRET", raising=False)
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "retry",
                "steps": [
                    {
                        "id": "fetch",
                        "type": "http",
                        "request": {
                            "method": "GET",
                            "url": "https://example.test",
                            "headers": {
                                "Authorization": {"secret": "FORGEFLOW_MISSING_TEST_SECRET"},
                            },
                        },
                        "retry": {"max_attempts": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(source),
            "--data-dir",
            str(directory),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["diagnostics"][0]["code"] == "SECRET_MISSING"
    assert not directory.exists()
