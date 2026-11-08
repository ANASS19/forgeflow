"""Bound input and YAML events before composing nodes; never invoke constructors."""

import math
import re
from pathlib import Path

import yaml
from pydantic import JsonValue, ValidationError
from yaml.events import (
    AliasEvent,
    CollectionEndEvent,
    CollectionStartEvent,
    DocumentStartEvent,
    NodeEvent,
    ScalarEvent,
)
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from forgeflow.workflow.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    WorkflowLoadError,
    schema_diagnostics,
)
from forgeflow.workflow.models import Workflow

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32
MAX_EVENTS = 20_000
MAX_INTEGER_CHARACTERS = 4096
_JSON_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


class _WorkflowLoader(yaml.SafeLoader):
    """Keep SafeLoader isolated; add JSON exponent recognition without construction."""


_WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?[eE][+-]?[0-9]+\Z"),
    list("-0123456789"),
)


def _failure(
    code: DiagnosticCode, *, line: int | None = None, column: int | None = None
) -> WorkflowLoadError:
    return WorkflowLoadError((Diagnostic(code, line=line, column=column),))


def _at_node(code: DiagnosticCode, node: Node) -> WorkflowLoadError:
    return _failure(code, line=node.start_mark.line + 1, column=node.start_mark.column + 1)


def _preflight(text: str) -> None:
    documents = depth = events = 0
    for event in yaml.parse(text, Loader=_WorkflowLoader):
        events += 1
        if events > MAX_EVENTS:
            raise _failure(DiagnosticCode.YAML_COMPLEXITY)
        if isinstance(event, DocumentStartEvent):
            documents += 1
            if documents > 1:
                raise _failure(DiagnosticCode.YAML_DOCUMENTS)
            if event.tags:
                raise _failure(DiagnosticCode.YAML_TAG)
        if isinstance(event, AliasEvent):
            raise _failure(DiagnosticCode.YAML_ALIAS)
        if isinstance(event, NodeEvent) and event.anchor is not None:
            raise _failure(DiagnosticCode.YAML_ANCHOR)
        if isinstance(event, (ScalarEvent, CollectionStartEvent)) and event.tag is not None:
            raise _failure(DiagnosticCode.YAML_TAG)
        if isinstance(event, CollectionStartEvent):
            depth += 1
            if depth > MAX_DEPTH:
                raise _failure(DiagnosticCode.YAML_DEPTH)
        elif isinstance(event, CollectionEndEvent):
            depth -= 1
    if documents != 1:
        raise _failure(DiagnosticCode.YAML_DOCUMENTS)


def _scalar(node: ScalarNode) -> str | int | float | bool | None:
    kind = node.tag.removeprefix("tag:yaml.org,2002:")
    value: str = node.value
    if kind == "str":
        return value
    if kind == "null" and value in {"null", ""}:
        return None
    if kind == "bool" and value in {"true", "false"}:
        return value == "true"
    if kind == "int" and _JSON_INTEGER.fullmatch(value):
        if len(value) > MAX_INTEGER_CHARACTERS:
            raise _at_node(DiagnosticCode.YAML_SCALAR, node)
        try:
            return int(value)
        except ValueError:
            raise _at_node(DiagnosticCode.YAML_SCALAR, node) from None
    if kind == "float":
        if value.lower().lstrip("+-") in {".nan", ".inf"}:
            raise _at_node(DiagnosticCode.YAML_NONFINITE, node)
        if _JSON_NUMBER.fullmatch(value):
            number = float(value)
            if not math.isfinite(number):
                raise _at_node(DiagnosticCode.YAML_NONFINITE, node)
            return number
    raise _at_node(DiagnosticCode.YAML_SCALAR, node)


def _construct(node: Node) -> JsonValue:
    if isinstance(node, ScalarNode):
        return _scalar(node)
    if isinstance(node, SequenceNode):
        return [_construct(child) for child in node.value]
    if isinstance(node, MappingNode):
        result: dict[str, JsonValue] = {}
        for key, child in node.value:
            if isinstance(key, ScalarNode) and key.value == "<<":
                raise _at_node(DiagnosticCode.YAML_MERGE, key)
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise _at_node(DiagnosticCode.YAML_KEY, key)
            name = key.value
            if name in result:
                raise _at_node(DiagnosticCode.YAML_DUPLICATE, key)
            result[name] = _construct(child)
        return result
    raise _at_node(DiagnosticCode.YAML_SCALAR, node)


def parse_workflow(content: bytes) -> Workflow:
    """Parse bounded UTF-8 bytes, returning a structurally valid schema-v1 workflow.

    Raises only sanitized WorkflowLoadError for invalid workflow input. Dependency
    existence, cycles, and reference targets are deliberately not checked here.
    """
    if len(content) > MAX_BYTES:
        raise _failure(DiagnosticCode.FILE_SIZE)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _failure(DiagnosticCode.ENCODING) from None
    try:
        _preflight(text)
        root = yaml.compose(text, Loader=_WorkflowLoader)
        if not isinstance(root, MappingNode):
            raise _failure(DiagnosticCode.YAML_ROOT)
        data = _construct(root)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        raise _failure(
            DiagnosticCode.YAML_SYNTAX,
            line=mark.line + 1 if mark else None,
            column=mark.column + 1 if mark else None,
        ) from None
    except yaml.YAMLError:
        raise _failure(DiagnosticCode.YAML_SYNTAX) from None
    except RecursionError:
        raise _failure(DiagnosticCode.YAML_DEPTH) from None
    try:
        return Workflow.model_validate(data)
    except ValidationError as error:
        raise WorkflowLoadError(schema_diagnostics(error)) from None


def load_workflow(path: str | Path) -> Workflow:
    """Read at most 1 MiB plus one byte; never include the path in diagnostics."""
    try:
        source = Path(path)
        if not source.is_file():
            raise _failure(DiagnosticCode.FILE_READ)
        with source.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
    except OSError:
        raise _failure(DiagnosticCode.FILE_READ) from None
    return parse_workflow(content)
