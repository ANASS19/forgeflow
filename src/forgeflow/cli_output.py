"""Human and machine output shared by the CLI command modules."""

import json

import typer


def emit(payload: dict[str, object], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps({"output_version": 1, **payload}, ensure_ascii=True))
        return
    typer.echo(str(payload.get("message", payload.get("status", ""))))
    findings = payload.get("diagnostics", [])
    for finding in findings if isinstance(findings, list) else []:
        if isinstance(finding, dict):
            typer.echo(f"{finding['code']}: {finding['message']} at {finding['location']}")
            if finding.get("related"):
                typer.echo(f"Cycle locations: {finding['related']}")
