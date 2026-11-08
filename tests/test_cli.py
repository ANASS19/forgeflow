"""Exercise the implemented public CLI without adding workflow commands."""

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forgeflow import __version__
from forgeflow.cli import app


@pytest.mark.parametrize("arguments", [[], ["--help"]])
def test_help(arguments: list[str]) -> None:
    result = CliRunner().invoke(app, arguments)

    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output
    assert "API developers" in result.output
    assert "--help" in result.output
    assert "--version" in result.output


def test_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == f"forgeflow {__version__}"


def test_unknown_option_fails_cleanly() -> None:
    result = CliRunner().invoke(app, ["--unknown-option"])

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("entrypoint", ["console", "module"])
def test_installed_entrypoint_outside_repository(entrypoint: str, tmp_path: Path) -> None:
    if entrypoint == "console":
        executable = Path(sysconfig.get_path("scripts")) / (
            "forgeflow.exe" if sys.platform == "win32" else "forgeflow"
        )
        command = [str(executable), "--version"]
    else:
        command = [sys.executable, "-I", "-m", "forgeflow", "--version"]

    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"forgeflow {__version__}"
