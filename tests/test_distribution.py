"""Build distributions and verify a wheel without editable-install leakage."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile

import pytest

from forgeflow import __version__


@dataclass(frozen=True)
class WheelInstallation:
    environment: Path
    working_directory: Path
    wheel: Path

    @property
    def scripts(self) -> Path:
        return self.environment / ("Scripts" if sys.platform == "win32" else "bin")

    @property
    def python(self) -> Path:
        return self.scripts / ("python.exe" if sys.platform == "win32" else "python")


def _run(
    arguments: list[str | Path],
    *,
    cwd: Path,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "COLUMNS": "120",
        **(extra_environment or {}),
    }
    result = subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory: pytest.TempPathFactory) -> WheelInstallation:
    uv = shutil.which("uv")
    assert uv is not None, "Install uv and run uv sync --locked before running packaging tests."
    project = Path(__file__).resolve().parents[1]
    workspace = tmp_path_factory.mktemp("wheel-install")
    artifacts = workspace / "dist"

    # uv builds the wheel from the sdist by default, checking both distribution paths.
    _run(
        [
            uv,
            "build",
            "--offline",
            "--no-build-isolation",
            "--no-sources",
            "--python",
            sys.executable,
            "--out-dir",
            artifacts,
        ],
        cwd=project,
    )
    wheels = list(artifacts.glob("*.whl"))
    assert len(wheels) == 1
    assert len(list(artifacts.glob("*.tar.gz"))) == 1

    installation = WheelInstallation(workspace / "environment", workspace, wheels[0])
    _run(
        [
            uv,
            "venv",
            "--no-project",
            "--no-python-downloads",
            "--python",
            sys.executable,
            installation.environment,
        ],
        cwd=workspace,
    )
    _run(
        [
            uv,
            "sync",
            "--locked",
            "--offline",
            "--no-dev",
            "--no-install-project",
            "--no-python-downloads",
            "--python",
            installation.python,
        ],
        cwd=project,
        extra_environment={"UV_PROJECT_ENVIRONMENT": str(installation.environment)},
    )
    _run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--python",
            installation.python,
            "--no-deps",
            installation.wheel,
        ],
        cwd=workspace,
    )
    _run([uv, "pip", "check", "--python", installation.python], cwd=workspace)
    return installation


def test_wheel_metadata_and_contents(installed_wheel: WheelInstallation) -> None:
    with ZipFile(installed_wheel.wheel) as wheel:
        names = wheel.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(wheel.read(metadata_name).decode("utf-8"))

    assert metadata["Name"] == "forgeflow"
    assert metadata["Version"] == __version__
    requires_python = metadata["Requires-Python"]
    assert requires_python is not None
    assert set(requires_python.split(",")) == {">=3.12", "<3.13"}
    assert metadata["License-Expression"] == "Apache-2.0"
    requirements = metadata.get_all("Requires-Dist", [])
    assert {
        re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0].lower()
        for requirement in requirements
    } == {"typer", "pydantic", "pyyaml", "sqlalchemy", "alembic"}
    assert "forgeflow/py.typed" in names
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
    assert not any(name.startswith(("tests/", ".venv/", ".git/")) for name in names)


def test_wheel_import_is_isolated(installed_wheel: WheelInstallation) -> None:
    result = _run(
        [
            installed_wheel.python,
            "-I",
            "-c",
            "import importlib.metadata, importlib.util, json, forgeflow; "
            "from forgeflow.workflow import parse_workflow; "
            'assert parse_workflow(b\'{"schema_version": 1, "name": "wheel", '
            '"steps": [{"id": "seed", "type": "value", "values": {"x": 1}}]}\').name '
            "== 'wheel'; "
            "assert importlib.util.find_spec('pytest') is None; "
            "assert forgeflow.__version__ == importlib.metadata.version('forgeflow'); "
            "print(json.dumps({'module': forgeflow.__file__}))",
        ],
        cwd=installed_wheel.working_directory,
    )

    module_path = Path(json.loads(result.stdout)["module"]).resolve()
    assert module_path.is_relative_to(installed_wheel.environment.resolve())


@pytest.mark.parametrize("entrypoint", ["console", "module"])
@pytest.mark.parametrize("arguments", [[], ["--help"], ["--version"]])
def test_wheel_cli_outside_repository(
    installed_wheel: WheelInstallation, entrypoint: str, arguments: list[str]
) -> None:
    command: list[str | Path]
    if entrypoint == "console":
        command = [
            installed_wheel.scripts / ("forgeflow.exe" if sys.platform == "win32" else "forgeflow")
        ]
    else:
        command = [installed_wheel.python, "-I", "-m", "forgeflow"]

    command.extend(arguments)
    result = _run(command, cwd=installed_wheel.working_directory)

    if arguments == ["--version"]:
        assert result.stdout.strip() == f"forgeflow {__version__}"
    else:
        assert "Usage:" in result.stdout
        assert "API developers" in result.stdout
        assert "--version" in result.stdout
