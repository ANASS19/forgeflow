"""Command-line entry point for the ForgeFlow package foundation."""

from typing import Annotated

import typer

from forgeflow import __version__

app = typer.Typer(
    name="forgeflow",
    help=(
        "ForgeFlow: local-first workflow debugging for API developers. "
        "This foundation release provides help and version information. "
        "Workflow commands are planned and are not available yet."
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
