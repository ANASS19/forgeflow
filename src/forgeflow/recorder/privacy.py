"""Approved values only: excluded data and its hashes never reach persistence."""

import json
from dataclasses import dataclass

from pydantic import JsonValue

from forgeflow.workflow.models import (
    AssertStep,
    HttpStep,
    LiteralOperand,
    ReferenceOperand,
    ValueStep,
    Workflow,
)

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set_cookie",
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "client_secret",
        "credential",
    }
)
MAX_CAPTURE_BYTES = 256 * 1024


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


@dataclass(frozen=True)
class Privacy:
    secrets: tuple[str, ...] = ()

    def restricted(self, value: JsonValue, *, name: str = "") -> bool:
        normalized = name.lower().replace("-", "_")
        if normalized in SENSITIVE_KEYS:
            return True
        if isinstance(value, str):
            return any(secret and secret in value for secret in self.secrets)
        if isinstance(value, dict):
            return any(self.restricted(child, name=key) for key, child in value.items())
        if isinstance(value, list):
            return any(self.restricted(child) for child in value)
        return False

    def record(self, value: JsonValue, *, name: str = "") -> dict[str, JsonValue]:
        if self.restricted(value, name=name):
            return {"availability": "redacted"}
        if len(encoded(value).encode()) > MAX_CAPTURE_BYTES:
            return {"availability": "too_large"}
        return {"availability": "present", "value": value}


def recording_plan(workflow: Workflow, privacy: Privacy) -> dict[str, JsonValue]:
    """Omit every HTTP destination, query, header, pointer, and secret variable name."""
    steps: list[JsonValue] = []
    for step in workflow.steps:
        entry: dict[str, JsonValue] = {
            "id": step.id,
            "type": step.type,
            "needs": list(step.needs),
            "attempt_timeout_seconds": step.attempt_timeout_seconds,
        }
        if isinstance(step, ValueStep):
            entry["values"] = {
                name: privacy.record(value, name=name) for name, value in step.values.items()
            }
        elif isinstance(step, AssertStep):
            entry["op"] = step.op
            for name, operand in (("left", step.left), ("right", step.right)):
                entry[name] = _operand(operand, privacy)
        elif isinstance(step, HttpStep):
            entry.update(
                {
                    "method": step.request.method,
                    "capture_names": list(step.capture),
                    "expect_status": list(step.expect_status),
                    "max_attempts": step.retry.max_attempts,
                }
            )
        steps.append(entry)
    return {
        "format_version": 1,
        "semantics_version": 1,
        "name": workflow.name,
        "execution": {
            "concurrency": workflow.execution.concurrency,
            "timeout_seconds": workflow.execution.timeout_seconds,
        },
        "defaults": {"attempt_timeout_seconds": workflow.defaults.attempt_timeout_seconds},
        "steps": steps,
    }


def _operand(operand: LiteralOperand | ReferenceOperand, privacy: Privacy) -> dict[str, JsonValue]:
    if isinstance(operand, ReferenceOperand):
        return {"ref": operand.ref}
    return {"literal": privacy.record(operand.literal)}
