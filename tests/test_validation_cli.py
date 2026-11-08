"""The validation CLI stays offline and emits versioned, sanitized results."""

import json
from pathlib import Path

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
