"""Deterministic JSON operands and built-in side-effect-free actions."""

from pydantic import JsonValue

from forgeflow.domain import ErrorCode, ForgeFlowError, Outcome, State
from forgeflow.workflow.models import (
    AssertStep,
    LiteralOperand,
    QueryLiteral,
    ReferenceOperand,
    ValueStep,
)


def resolve(
    operand: LiteralOperand | QueryLiteral | ReferenceOperand,
    outputs: dict[str, dict[str, JsonValue]],
) -> JsonValue:
    if isinstance(operand, ReferenceOperand):
        producer, _, name = operand.ref.split(".")
        if producer not in outputs or name not in outputs[producer]:
            raise ForgeFlowError(ErrorCode.OUTPUT_UNAVAILABLE)
        return outputs[producer][name]
    return operand.literal


def json_equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def execute_pure(step: ValueStep | AssertStep, outputs: dict[str, dict[str, JsonValue]]) -> Outcome:
    if isinstance(step, ValueStep):
        return Outcome(State.SUCCEEDED, dict(step.values))
    if json_equal(resolve(step.left, outputs), resolve(step.right, outputs)):
        return Outcome(State.SUCCEEDED, {"passed": True})
    return Outcome(State.FAILED, code=ErrorCode.ASSERTION_FAILED)
