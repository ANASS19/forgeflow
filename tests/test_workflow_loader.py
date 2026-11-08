"""Adversarial YAML, byte limits, and parser isolation at the public boundary."""

import io
import json
import sys
from pathlib import Path
from typing import BinaryIO

import pytest
import yaml

from forgeflow.workflow import DiagnosticCode as Code
from forgeflow.workflow import WorkflowLoadError, load_workflow, parse_workflow
from forgeflow.workflow.loader import MAX_BYTES
from forgeflow.workflow.models import HttpStep, ValueStep

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
VALID = b"schema_version: 1\nname: test\nsteps:\n- id: seed\n  type: value\n  values: {count: 1}\n"


def _fails(content: bytes, code: Code) -> WorkflowLoadError:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)
    assert caught.value.diagnostics[0].code == code
    return caught.value


@pytest.mark.parametrize("name", ["values.yaml", "api-health.yaml"])
def test_valid_examples(name: str) -> None:
    workflow = load_workflow(EXAMPLES / name)
    assert workflow.schema_version == 1
    assert len(workflow.steps) == 2


@pytest.mark.parametrize(
    ("name", "code"),
    [("head-capture.yaml", Code.HEAD_CAPTURE), ("duplicate-key.yaml", Code.YAML_DUPLICATE)],
)
def test_invalid_examples(name: str, code: Code) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        load_workflow(EXAMPLES / "invalid" / name)
    assert caught.value.diagnostics[0].code == code


@pytest.mark.parametrize("source", [b"name: [", b"name: {x: y", b'name: "unterminated'])
def test_invalid_syntax_has_positions(source: bytes) -> None:
    error = _fails(source, Code.YAML_SYNTAX)
    assert error.diagnostics[0].line is not None
    assert error.diagnostics[0].column is not None


@pytest.mark.parametrize("source", [b"", b"# empty\n", b"{}\n---\n{}", b"---\n{}\n---\n"])
def test_document_count(source: bytes) -> None:
    _fails(source, Code.YAML_DOCUMENTS)


@pytest.mark.parametrize("source", [b"[]", b"hello", b"null", b"---\n", b"42", b"true"])
def test_root_must_be_mapping(source: bytes) -> None:
    _fails(source, Code.YAML_ROOT)


@pytest.mark.parametrize(
    "source",
    [b"name: one\nname: two", b"outer: {inner: 1, inner: 2}", b'"a": 1\na: 2'],
)
def test_duplicate_keys_at_every_level(source: bytes) -> None:
    _fails(source, Code.YAML_DUPLICATE)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (b"x: &anchor value", Code.YAML_ANCHOR),
        (b"x: &anchor []", Code.YAML_ANCHOR),
        (b"x: *unknown", Code.YAML_ALIAS),
        (b"x: !!str value", Code.YAML_TAG),
        (b"x: !custom value", Code.YAML_TAG),
        (b"x: ! value", Code.YAML_TAG),
        (b"%TAG !e! tag:example.test,2026:\n---\nx: 1", Code.YAML_TAG),
        (b"x: {<<: {a: 1}}", Code.YAML_MERGE),
        (b'x: {"<<": {a: 1}}', Code.YAML_MERGE),
        (b"x: {1: a}", Code.YAML_KEY),
        (b"? [a, b]\n: value", Code.YAML_KEY),
    ],
)
def test_forbidden_yaml_features(source: bytes, code: Code) -> None:
    _fails(source, code)


@pytest.mark.parametrize(
    "source",
    [
        b"!!python/object/apply:builtins.print [MALICIOUS_PRINT_CANARY]",
        b"!!python/name:builtins.eval ''",
        b"!!python/object/new:builtins.object {}",
        b"x: !!binary Zm9v",
        b"x: !!set {a: null}",
    ],
)
def test_malicious_constructors_never_run(
    source: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    _fails(source, Code.YAML_TAG)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize(
    "value",
    [
        "yes",
        "no",
        "on",
        "off",
        "~",
        "True",
        "Null",
        "012",
        "0xFF",
        "+1",
        "1:20",
        "2026-11-08",
        "2026-11-08T10:00:00Z",
    ],
)
def test_unsupported_yaml_scalar_forms(value: str) -> None:
    _fails(f"x: {value}".encode(), Code.YAML_SCALAR)


@pytest.mark.parametrize("value", [".nan", ".inf", "-.Inf", "+.INF", "1e9999", "-1.0e9999"])
def test_nonfinite_numbers(value: str) -> None:
    _fails(f"x: [{{nested: {value}}}]".encode(), Code.YAML_NONFINITE)


def test_json_scalar_values_and_exponents() -> None:
    source = VALID.replace(
        b"{count: 1}",
        b'{count: 1, negative: -2, ratio: 1e2, flag: true, empty: null, text: "yes"}',
    )
    workflow = parse_workflow(source)
    step = workflow.steps[0]
    assert isinstance(step, ValueStep)
    assert step.values == {
        "count": 1,
        "negative": -2,
        "ratio": 100.0,
        "flag": True,
        "empty": None,
        "text": "yes",
    }
    assert type(step.values["flag"]) is bool
    assert type(step.values["count"]) is int


def test_oversized_integer_fails_safely() -> None:
    _fails(b"x: " + b"9" * 5000, Code.YAML_SCALAR)


def test_integer_budget_does_not_depend_on_interpreter_settings() -> None:
    previous_limit = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        _fails(b"x: " + b"9" * 4097, Code.YAML_SCALAR)
    finally:
        sys.set_int_max_str_digits(previous_limit)


@pytest.mark.parametrize("source", [b"\xff", b"\x00", "name: test".encode("utf-16")])
def test_invalid_encoding_or_yaml_characters(source: bytes) -> None:
    with pytest.raises(WorkflowLoadError):
        parse_workflow(source)


def test_utf8_bom_and_unicode_literals() -> None:
    source = VALID.replace(b"{count: 1}", '{greeting: "ciao 世界"}'.encode())
    workflow = parse_workflow(b"\xef\xbb\xbf" + source)
    assert isinstance(workflow.steps[0], ValueStep)
    assert workflow.steps[0].values["greeting"] == "ciao 世界"


def test_exact_file_size_limit() -> None:
    padded = VALID + b"#" + b"a" * (MAX_BYTES - len(VALID) - 1)
    assert parse_workflow(padded).name == "test"
    _fails(padded + b"a", Code.FILE_SIZE)


def test_size_limit_counts_utf8_bytes() -> None:
    _fails(VALID + b"#" + "世".encode() * (MAX_BYTES // 3 + 1), Code.FILE_SIZE)


@pytest.mark.parametrize(("nested_lists", "valid"), [(28, True), (29, False), (1000, False)])
def test_collection_depth_boundary(nested_lists: int, valid: bool) -> None:
    source = VALID.replace(
        b"{count: 1}", b"{payload: " + b"[" * nested_lists + b"0" + b"]" * nested_lists + b"}"
    )
    if valid:
        assert parse_workflow(source).name == "test"
    else:
        _fails(source, Code.YAML_DEPTH)


def test_event_budget_limits_wide_documents() -> None:
    _fails(json.dumps({"x": [0] * 20_001}).encode(), Code.YAML_COMPLEXITY)


def test_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_bytes(VALID)
    read_sizes: list[int | None] = []

    class ObservedStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            read_sizes.append(size)
            return super().read(size)

    def bounded_open(self: Path, mode: str) -> BinaryIO:
        return ObservedStream(b"a" * (MAX_BYTES + 100))

    monkeypatch.setattr(Path, "open", bounded_open)
    with pytest.raises(WorkflowLoadError) as caught:
        load_workflow(path)
    assert caught.value.diagnostics[0].code == Code.FILE_SIZE
    assert read_sizes == [MAX_BYTES + 1]


def test_unreadable_paths_are_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "SYNTHETIC_PRIVATE_PATH.yaml"
    with pytest.raises(WorkflowLoadError) as missing:
        load_workflow(path)
    assert "SYNTHETIC_PRIVATE_PATH" not in str(missing.value)
    path.write_bytes(VALID)

    def denied(self: Path, mode: str) -> BinaryIO:
        raise PermissionError("SYNTHETIC_PRIVATE_PATH")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(WorkflowLoadError) as caught:
        load_workflow(path)
    assert caught.value.diagnostics[0].code == Code.FILE_READ
    assert "SYNTHETIC_PRIVATE_PATH" not in str(caught.value)


def test_directory_is_not_a_workflow(tmp_path: Path) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        load_workflow(tmp_path)
    assert caught.value.diagnostics[0].code == Code.FILE_READ


def test_loader_does_not_modify_global_yaml_resolution() -> None:
    before = yaml.safe_load("x: 1e2")
    parse_workflow(VALID)
    assert yaml.safe_load("x: 1e2") == before == {"x": "1e2"}


def test_http_example_does_not_read_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORGEFLOW_EXAMPLE_TOKEN", raising=False)
    workflow = load_workflow(EXAMPLES / "api-health.yaml")
    assert isinstance(workflow.steps[0], HttpStep)
    assert workflow.steps[0].request.method == "GET"
