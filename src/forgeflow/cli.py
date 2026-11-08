"""Command-line entry point for the ForgeFlow package foundation."""

from pathlib import Path
from typing import Annotated

import typer

from forgeflow import __version__
from forgeflow.cli_output import emit
from forgeflow.doctor import check_workflow
from forgeflow.runtime_cli import register
from forgeflow.workflow import WorkflowLoadError, load_workflow
from forgeflow.workflow.graph import build_graph

app = typer.Typer(
    name="forgeflow",
    help=(
        "ForgeFlow: local-first workflow debugging for API developers. "
        "Validate YAML, diagnose configuration, and execute value/assert workflows "
        "with local history."
    ),
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)


@app.callback()
def main(
    context: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Show the installed ForgeFlow version and exit.", is_eager=True
        ),
    ] = False,
) -> None:
    """Display package information until workflow commands are implemented."""
    if version:
        typer.echo(f"forgeflow {__version__}")
        raise typer.Exit()

    if context.invoked_subcommand is None:
        typer.echo(context.get_help())


def _check(file: Path, *, doctor: bool, check_env: bool, json_output: bool) -> None:
    try:
        workflow = load_workflow(file)
        graph = build_graph(workflow)
        findings = check_workflow(workflow, check_env=check_env) if doctor else ()
        failed = any(item.severity == "error" for item in findings)
        emit(
            {
                "status": "invalid" if failed else "valid",
                "step_count": len(graph.order),
                "message": "Workflow has errors." if failed else "Workflow is valid.",
                "diagnostics": [item.to_dict() for item in findings],
            },
            json_output=json_output,
        )
        if failed:
            raise typer.Exit(2)
    except WorkflowLoadError as error:
        emit(
            {
                "status": "invalid",
                "message": "Workflow validation failed.",
                "diagnostics": [item.to_dict() for item in error.diagnostics],
            },
            json_output=json_output,
        )
        raise typer.Exit(2) from None


@app.command()
def validate(file: Path, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Validate YAML, dependency edges, references, and cycles without side effects."""
    _check(file, doctor=False, check_env=False, json_output=json_output)


@app.command()
def doctor(
    file: Path,
    check_env: Annotated[bool, typer.Option("--check-env")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain workflow problems; optionally check secret presence without displaying values."""
    _check(file, doctor=True, check_env=check_env, json_output=json_output)


register(app)
