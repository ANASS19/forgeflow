"""DAG and reference contracts, including stable ordering and concrete cycle paths."""

import json
import random

import pytest

from forgeflow.workflow import WorkflowLoadError, parse_workflow
from forgeflow.workflow.graph import build_graph


def _workflow(steps: list[dict[str, object]]) -> bytes:
    return json.dumps({"schema_version": 1, "name": "graph", "steps": steps}).encode()


def _value(name: str, needs: list[str]) -> dict[str, object]:
    return {"id": name, "type": "value", "needs": needs, "values": {"n": 1}}


def test_diamond_stable_order() -> None:
    graph = build_graph(
        parse_workflow(
            _workflow(
                [
                    _value("end", ["a", "b"]),
                    _value("a", ["start"]),
                    _value("b", ["start"]),
                    _value("start", []),
                ]
            )
        )
    )
    assert graph.order == ("start", "a", "b", "end")
    assert graph.successors["start"] == ("a", "b")


@pytest.mark.parametrize(
    "needs,code", [(["missing"], "DEPENDENCY_MISSING"), (["a"], "DEPENDENCY_SELF")]
)
def test_invalid_dependency(needs: list[str], code: str) -> None:
    with pytest.raises(WorkflowLoadError) as error:
        build_graph(parse_workflow(_workflow([_value("a", needs)])))
    assert error.value.diagnostics[0].code == code


def test_actual_cycle_excludes_blocked_descendant() -> None:
    with pytest.raises(WorkflowLoadError) as error:
        build_graph(
            parse_workflow(
                _workflow(
                    [
                        _value("a", ["b"]),
                        _value("b", ["a"]),
                        _value("blocked", ["b"]),
                    ]
                )
            )
        )
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "DEPENDENCY_CYCLE"
    assert diagnostic.related == (("steps", 0), ("steps", 1), ("steps", 0))


@pytest.mark.parametrize(
    "ref,needs,code",
    [
        ("missing.outputs.n", [], "REFERENCE_STEP_MISSING"),
        ("seed.outputs.missing", ["seed"], "REFERENCE_OUTPUT_MISSING"),
        ("seed.outputs.n", [], "REFERENCE_DEPENDENCY_REQUIRED"),
        ("seed.outputs.n", ["seed"], None),
    ],
)
def test_reference_contract(ref: str, needs: list[str], code: str | None) -> None:
    workflow = parse_workflow(
        _workflow(
            [
                _value("seed", []),
                {
                    "id": "check",
                    "type": "assert",
                    "needs": needs,
                    "left": {"ref": ref},
                    "op": "eq",
                    "right": {"literal": 1},
                },
            ]
        )
    )
    if code:
        with pytest.raises(WorkflowLoadError) as error:
            build_graph(workflow)
        assert error.value.diagnostics[0].code == code
    else:
        assert build_graph(workflow).order == ("seed", "check")


def test_seeded_dags_preserve_all_edges() -> None:
    rng = random.Random(19)
    for _ in range(40):
        steps = [
            _value(f"s{i}", [f"s{j}" for j in range(i) if rng.random() < 0.15]) for i in range(30)
        ]
        rng.shuffle(steps)
        graph = build_graph(parse_workflow(_workflow(steps)))
        position = {name: index for index, name in enumerate(graph.order)}
        assert all(
            position[parent] < position[child]
            for child, parents in graph.predecessors.items()
            for parent in parents
        )
