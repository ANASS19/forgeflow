"""Execution/history commands; user input never appears in infrastructure errors."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.exc import SQLAlchemyError

from forgeflow.cli_output import emit
from forgeflow.config import data_directory
from forgeflow.doctor import check_workflow
from forgeflow.domain import ErrorCode, ForgeFlowError, exit_code
from forgeflow.engine.http import HttpHandler
from forgeflow.engine.runner import execute
from forgeflow.storage.repository import Repository, Snapshot
from forgeflow.workflow import WorkflowLoadError, load_workflow
from forgeflow.workflow.graph import build_graph

JsonOption = Annotated[bool, typer.Option("--json")]
DirectoryOption = Annotated[
    Path | None, typer.Option("--data-dir", help="Override local data directory.")
]


@contextmanager
def errors(json_output: bool) -> Iterator[None]:
    try:
        yield
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
    except ForgeFlowError as error:
        emit(
            {
                "status": "error",
                "code": error.code,
                "message": (
                    "HTTP retries beyond one attempt are not implemented in this checkpoint."
                    if error.code == ErrorCode.ACTION_UNAVAILABLE
                    else error.code.value
                ),
            },
            json_output=json_output,
        )
        raise typer.Exit(
            2
            if error.code
            in {
                ErrorCode.ACTION_UNAVAILABLE,
                ErrorCode.SECRET_MISSING,
                ErrorCode.SECRET_HEADER_INVALID,
            }
            or error.code.value.startswith("REPLAY_")
            else 3
        ) from None
    except (SQLAlchemyError, OSError, ValueError):
        emit(
            {
                "status": "error",
                "code": ErrorCode.STORAGE,
                "message": "Local storage is unavailable.",
            },
            json_output=json_output,
        )
        raise typer.Exit(3) from None


def inspect_payload(snapshot: Snapshot) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "name": snapshot.name,
        "parent_id": snapshot.parent_id,
        "mode": snapshot.mode,
        "state": snapshot.state,
        "steps": [
            {"id": name, "state": state, "causes": snapshot.causes[name]}
            for name, state in snapshot.steps.items()
        ],
        "attempts": [asdict(attempt) for attempt in snapshot.attempts],
        "outputs": {
            step: {name: value["availability"] for name, value in values.items()}
            for step, values in snapshot.values.items()
        },
        "events": [asdict(event) for event in snapshot.events],
    }


def run(
    file: Path,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    data_dir: DirectoryOption = None,
    json_output: JsonOption = False,
) -> None:
    """Execute a workflow with pure steps or HTTP GET/HEAD; parent links never reuse outputs."""
    with errors(json_output):
        workflow = load_workflow(file)
        build_graph(workflow)
        findings = tuple(
            item for item in check_workflow(workflow, check_env=True) if item.severity == "error"
        )
        if findings:
            raise WorkflowLoadError(findings)
        handler = HttpHandler(workflow)
        directory = data_directory(data_dir)
        with Repository(directory, writable=True) as repository:
            result = asyncio.run(
                execute(
                    workflow,
                    repository,
                    parent_id=parent,
                    handler=handler,
                    progress=None
                    if json_output
                    else lambda name, state: typer.echo(f"{name}: {state}", err=True),
                )
            )
        emit(
            {
                "id": result.id,
                "state": result.state,
                "steps": dict(result.steps),
                "message": f"Run {result.id}: {result.state}",
            },
            json_output=json_output,
        )
        raise typer.Exit(exit_code(result.state))


def inspect_run(
    run_id: str, data_dir: DirectoryOption = None, json_output: JsonOption = False
) -> None:
    """Inspect attempt evidence and capture availability without displaying recorded values."""
    with errors(json_output):
        with Repository(data_directory(data_dir)) as repository:
            snapshot = repository.snapshot(run_id)
            payload = inspect_payload(snapshot)
        payload["message"] = f"Run {payload['id']}: {payload['state']}\n" + "\n".join(
            f"{name}: {state}" for name, state in snapshot.steps.items()
        )
        emit(payload, json_output=json_output)


history_app = typer.Typer(
    help="Inspect or explicitly prune local history.", invoke_without_command=True
)


@history_app.callback()
def history(
    context: typer.Context, data_dir: DirectoryOption = None, json_output: JsonOption = False
) -> None:
    if context.invoked_subcommand is not None:
        return
    with errors(json_output):
        directory = data_directory(data_dir)
        rows = []
        if (directory / "history.sqlite3").is_file():
            with Repository(directory) as repository:
                rows = repository.history()
        emit(
            {
                "runs": rows,
                "message": "\n".join(f"{row['id']} {row['state']} {row['name']}" for row in rows)
                or "No execution history.",
            },
            json_output=json_output,
        )


@history_app.command()
def prune(
    older_than: Annotated[int, typer.Option("--older-than", min=1)],
    data_dir: DirectoryOption = None,
    json_output: JsonOption = False,
) -> None:
    """Delete terminal history older than the specified number of days."""
    with errors(json_output):
        with Repository(data_directory(data_dir), writable=True) as repository:
            count = repository.prune(older_than)
        emit({"deleted": count, "message": f"Deleted {count} runs."}, json_output=json_output)


def recover(data_dir: DirectoryOption = None, json_output: JsonOption = False) -> None:
    """Mark abandoned executions interrupted; never dispatch requests or resume steps."""
    with errors(json_output):
        directory = data_directory(data_dir)
        ids: list[str] = []
        if (directory / "history.sqlite3").is_file():
            with Repository(directory, writable=True) as repository:
                ids = repository.recover()
        emit(
            {"recovered": ids, "message": f"Marked {len(ids)} runs INTERRUPTED."},
            json_output=json_output,
        )


def register(app: typer.Typer) -> None:
    app.command()(run)
    app.command("inspect")(inspect_run)
    app.command()(recover)
    app.add_typer(history_app, name="history")
