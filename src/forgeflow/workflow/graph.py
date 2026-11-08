"""Explicit DAG edges, reference contracts, stable ordering, and real cycle paths."""

import heapq
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from forgeflow.workflow.diagnostics import Diagnostic, WorkflowLoadError
from forgeflow.workflow.diagnostics import DiagnosticCode as Code
from forgeflow.workflow.models import AssertStep, HttpStep, ReferenceOperand, ValueStep, Workflow

type WorkflowStep = ValueStep | HttpStep | AssertStep


@dataclass(frozen=True)
class WorkflowGraph:
    order: tuple[str, ...]
    predecessors: Mapping[str, tuple[str, ...]]
    successors: Mapping[str, tuple[str, ...]]


def output_names(step: WorkflowStep) -> set[str]:
    if isinstance(step, ValueStep):
        return set(step.values)
    if isinstance(step, HttpStep):
        return {"status_code", *step.capture}
    return {"passed"}


def references(step: WorkflowStep) -> list[tuple[tuple[str | int, ...], ReferenceOperand]]:
    if isinstance(step, AssertStep):
        return [
            (name, operand)
            for name, operand in [(("left",), step.left), (("right",), step.right)]
            if isinstance(operand, ReferenceOperand)
        ]
    if isinstance(step, HttpStep):
        return [
            (("request", "query", index), operand)
            for index, operand in enumerate(step.request.query.values())
            if isinstance(operand, ReferenceOperand)
        ]
    return []


def build_graph(workflow: Workflow) -> WorkflowGraph:
    steps = {step.id: step for step in workflow.steps}
    indexes = {step.id: index for index, step in enumerate(workflow.steps)}
    errors: list[Diagnostic] = []
    for index, step in enumerate(workflow.steps):
        for position, parent in enumerate(step.needs):
            dependency_code = Code.DEPENDENCY_SELF if parent == step.id else Code.DEPENDENCY_MISSING
            if parent == step.id or parent not in steps:
                errors.append(Diagnostic(dependency_code, ("steps", index, "needs", position)))
        for location, operand in references(step):
            parent, _, output = operand.ref.split(".")
            code: Code | None = None
            if parent not in steps:
                code = Code.REFERENCE_MISSING
            elif output not in output_names(steps[parent]):
                code = Code.REFERENCE_OUTPUT
            elif parent not in step.needs:
                code = Code.REFERENCE_DEPENDENCY
            if code is not None:
                errors.append(Diagnostic(code, ("steps", index, *location, "ref")))
    if errors:
        raise WorkflowLoadError(tuple(errors[:50]))
    successors: dict[str, list[str]] = {name: [] for name in steps}
    remaining = {step.id: len(step.needs) for step in workflow.steps}
    for step in workflow.steps:
        for parent in step.needs:
            successors[parent].append(step.id)
    ready = [indexes[name] for name, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        name = workflow.steps[heapq.heappop(ready)].id
        order.append(name)
        for child in successors[name]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, indexes[child])
    if len(order) != len(steps):
        cycle = _find_cycle({name for name, count in remaining.items() if count}, successors)
        raise WorkflowLoadError(
            (
                Diagnostic(
                    Code.CYCLE,
                    ("steps",),
                    related=tuple(("steps", indexes[name]) for name in cycle),
                ),
            )
        )
    return WorkflowGraph(
        tuple(order),
        MappingProxyType({step.id: tuple(step.needs) for step in workflow.steps}),
        MappingProxyType({name: tuple(children) for name, children in successors.items()}),
    )


def _find_cycle(nodes: set[str], successors: dict[str, list[str]]) -> list[str]:
    visited: set[str] = set()
    active: list[str] = []

    def visit(name: str) -> list[str]:
        if name in active:
            return active[active.index(name) :] + [name]
        if name in visited:
            return []
        visited.add(name)
        active.append(name)
        for child in successors[name]:
            if child in nodes and (found := visit(child)):
                return found
        active.pop()
        return []

    for name in successors:
        if name in nodes and (found := visit(name)):
            return found
    raise RuntimeError("Cycle detection invariant violated.")
