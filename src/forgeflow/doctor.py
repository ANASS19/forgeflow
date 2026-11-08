"""Offline workflow checks; suggestions are distinct from validation errors."""

import os

from forgeflow.workflow.diagnostics import Diagnostic
from forgeflow.workflow.diagnostics import DiagnosticCode as Code
from forgeflow.workflow.models import HeaderSecret, HttpStep, Workflow


def check_workflow(workflow: Workflow, *, check_env: bool = False) -> tuple[Diagnostic, ...]:
    findings: list[Diagnostic] = []
    for index, step in enumerate(workflow.steps):
        if not isinstance(step, HttpStep):
            continue
        if step.request.method == "GET" and not step.capture:
            findings.append(
                Diagnostic(Code.CAPTURE_NONE, ("steps", index, "capture"), severity="warning")
            )
        timeout = step.attempt_timeout_seconds or workflow.defaults.attempt_timeout_seconds
        if timeout * step.retry.max_attempts > workflow.execution.timeout_seconds:
            findings.append(
                Diagnostic(Code.RETRY_BUDGET, ("steps", index, "retry"), severity="warning")
            )
        if check_env:
            for position, header in enumerate(step.request.headers.values()):
                if isinstance(header, HeaderSecret) and not os.environ.get(header.secret):
                    findings.append(
                        Diagnostic(
                            Code.SECRET_MISSING, ("steps", index, "request", "headers", position)
                        )
                    )
    return tuple(findings)
