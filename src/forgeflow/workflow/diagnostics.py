"""Allowlisted diagnostics that never serialize rejected input or parser messages."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError


class DiagnosticCode(StrEnum):
    FILE_READ = "WORKFLOW_READ_ERROR"
    FILE_SIZE = "WORKFLOW_TOO_LARGE"
    ENCODING = "WORKFLOW_UTF8_REQUIRED"
    YAML_SYNTAX = "YAML_SYNTAX_INVALID"
    YAML_DOCUMENTS = "YAML_DOCUMENT_COUNT"
    YAML_ROOT = "YAML_ROOT_MAPPING_REQUIRED"
    YAML_ANCHOR = "YAML_ANCHOR_FORBIDDEN"
    YAML_ALIAS = "YAML_ALIAS_FORBIDDEN"
    YAML_TAG = "YAML_TAG_FORBIDDEN"
    YAML_MERGE = "YAML_MERGE_FORBIDDEN"
    YAML_DUPLICATE = "YAML_DUPLICATE_KEY"
    YAML_KEY = "YAML_STRING_KEY_REQUIRED"
    YAML_SCALAR = "YAML_SCALAR_UNSUPPORTED"
    YAML_NONFINITE = "YAML_NUMBER_NONFINITE"
    YAML_DEPTH = "YAML_DEPTH_EXCEEDED"
    YAML_COMPLEXITY = "YAML_COMPLEXITY_EXCEEDED"
    REQUIRED = "SCHEMA_FIELD_REQUIRED"
    UNKNOWN = "SCHEMA_FIELD_UNKNOWN"
    TYPE = "SCHEMA_TYPE_INVALID"
    FORMAT = "SCHEMA_FORMAT_INVALID"
    BOUNDS = "SCHEMA_BOUND_VIOLATION"
    VALUE = "SCHEMA_VALUE_UNSUPPORTED"
    VERSION = "SCHEMA_VERSION_UNSUPPORTED"
    STEP_TYPE = "STEP_TYPE_UNSUPPORTED"
    STEP_DUPLICATE = "STEP_ID_DUPLICATE"
    NEEDS_DUPLICATE = "STEP_NEEDS_DUPLICATE"
    URL = "HTTP_URL_INVALID"
    HEADER = "HTTP_HEADER_INVALID"
    HEADER_SECRET = "HTTP_HEADER_SECRET_REQUIRED"
    QUERY = "HTTP_QUERY_INVALID"
    CAPTURE = "HTTP_CAPTURE_INVALID"
    HEAD_CAPTURE = "HTTP_HEAD_CAPTURE_FORBIDDEN"
    TRUNCATED = "DIAGNOSTICS_TRUNCATED"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DEPENDENCY_SELF = "DEPENDENCY_SELF"
    CYCLE = "DEPENDENCY_CYCLE"
    REFERENCE_MISSING = "REFERENCE_STEP_MISSING"
    REFERENCE_OUTPUT = "REFERENCE_OUTPUT_MISSING"
    REFERENCE_DEPENDENCY = "REFERENCE_DEPENDENCY_REQUIRED"
    CAPTURE_NONE = "DOCTOR_CAPTURE_NONE"
    RETRY_BUDGET = "DOCTOR_RETRY_BUDGET"
    SECRET_MISSING = "SECRET_MISSING"


_MESSAGES = {
    DiagnosticCode.FILE_READ: "The workflow must be a readable regular file.",
    DiagnosticCode.FILE_SIZE: "The workflow exceeds the 1 MiB input limit.",
    DiagnosticCode.ENCODING: "The workflow must use valid UTF-8 encoding.",
    DiagnosticCode.YAML_SYNTAX: "The workflow contains invalid YAML syntax.",
    DiagnosticCode.YAML_DOCUMENTS: "Exactly one YAML document is required.",
    DiagnosticCode.YAML_ROOT: "The YAML document root must be a mapping.",
    DiagnosticCode.YAML_ANCHOR: "YAML anchors are not supported.",
    DiagnosticCode.YAML_ALIAS: "YAML aliases are not supported.",
    DiagnosticCode.YAML_TAG: "Explicit YAML tags and tag directives are not supported.",
    DiagnosticCode.YAML_MERGE: "YAML merge keys are not supported.",
    DiagnosticCode.YAML_DUPLICATE: "Mapping keys must be unique.",
    DiagnosticCode.YAML_KEY: "Mapping keys must be strings.",
    DiagnosticCode.YAML_SCALAR: "Use JSON-compatible scalars; quote YAML-specific scalar forms.",
    DiagnosticCode.YAML_NONFINITE: "Numeric values must be finite.",
    DiagnosticCode.YAML_DEPTH: "YAML collection nesting exceeds the limit of 32.",
    DiagnosticCode.YAML_COMPLEXITY: "YAML parsing exceeds the limit of 20,000 events.",
    DiagnosticCode.REQUIRED: "A required field is missing.",
    DiagnosticCode.UNKNOWN: "An unknown field is not permitted.",
    DiagnosticCode.TYPE: "The field has an invalid type; implicit coercion is not supported.",
    DiagnosticCode.FORMAT: "The field does not match its required format.",
    DiagnosticCode.BOUNDS: "The field is outside its permitted size or numeric bounds.",
    DiagnosticCode.VALUE: "The field contains an unsupported option.",
    DiagnosticCode.VERSION: "The schema version must be the integer 1.",
    DiagnosticCode.STEP_TYPE: "The step type must be value, http, or assert.",
    DiagnosticCode.STEP_DUPLICATE: "Step IDs must be unique within a workflow.",
    DiagnosticCode.NEEDS_DUPLICATE: "A dependency may appear only once in needs.",
    DiagnosticCode.URL: "Use an absolute HTTP(S) URL without credentials, query, or fragment.",
    DiagnosticCode.HEADER: "Headers must be valid, unambiguous, and not transport-managed.",
    DiagnosticCode.HEADER_SECRET: "Credential headers require an environment-secret reference.",
    DiagnosticCode.QUERY: "Query keys must be safe and must not designate credentials.",
    DiagnosticCode.CAPTURE: "Use a non-root JSON pointer and do not overwrite status_code.",
    DiagnosticCode.HEAD_CAPTURE: "HEAD requests cannot declare JSON-body captures.",
    DiagnosticCode.TRUNCATED: "Additional validation diagnostics have been omitted.",
    DiagnosticCode.DEPENDENCY_MISSING: "The dependency does not identify a declared step.",
    DiagnosticCode.DEPENDENCY_SELF: "A step cannot depend on itself.",
    DiagnosticCode.CYCLE: "Dependencies contain a cycle; related locations show the cycle path.",
    DiagnosticCode.REFERENCE_MISSING: "The reference producer does not identify a declared step.",
    DiagnosticCode.REFERENCE_OUTPUT: "The referenced output is not declared by its producer.",
    DiagnosticCode.REFERENCE_DEPENDENCY: "A reference producer must be explicitly listed in needs.",
    DiagnosticCode.CAPTURE_NONE: "No response fields are captured; only HTTP status is available.",
    DiagnosticCode.RETRY_BUDGET: "The worst-case attempt budget exceeds the workflow deadline.",
    DiagnosticCode.SECRET_MISSING: "A required environment-secret variable is absent or empty.",
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: DiagnosticCode
    location: tuple[str | int, ...] = ()
    line: int | None = None
    column: int | None = None
    severity: Literal["error", "warning", "info"] = "error"
    related: tuple[tuple[str | int, ...], ...] = ()

    @property
    def message(self) -> str:
        return _MESSAGES[self.code]

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code.value,
            "location": list(self.location),
            "message": self.message,
        }
        if self.line is not None:
            result["line"] = self.line
        if self.column is not None:
            result["column"] = self.column
        if self.severity != "error":
            result["severity"] = self.severity
        if self.related:
            result["related"] = [list(location) for location in self.related]
        return result


class WorkflowLoadError(Exception):
    """The public loading error; all attached diagnostics are safe to display."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.code.value}: {item.message}" for item in diagnostics))


_FIELDS = frozenset(
    "schema_version name execution concurrency timeout_seconds defaults attempt_timeout_seconds "
    "steps id type needs values request method url query headers literal ref secret prefix "
    "expect_status capture retry max_attempts left op right".split()
)
_VARIANTS = frozenset(
    {
        "value",
        "http",
        "assert",
        "LiteralOperand",
        "ReferenceOperand",
        "QueryLiteral",
        "HeaderLiteral",
        "HeaderSecret",
    }
)
_ERROR_CODES = {
    "missing": DiagnosticCode.REQUIRED,
    "extra_forbidden": DiagnosticCode.UNKNOWN,
    "literal_error": DiagnosticCode.VALUE,
    "union_tag_invalid": DiagnosticCode.STEP_TYPE,
    "union_tag_not_found": DiagnosticCode.REQUIRED,
    "string_pattern_mismatch": DiagnosticCode.FORMAT,
    **dict.fromkeys(
        (
            "greater_than",
            "greater_than_equal",
            "less_than",
            "less_than_equal",
            "too_long",
            "too_short",
            "string_too_long",
            "string_too_short",
        ),
        DiagnosticCode.BOUNDS,
    ),
}


def schema_diagnostics(error: ValidationError) -> tuple[Diagnostic, ...]:
    """Discard raw messages, context, input, and user-defined mapping keys."""
    diagnostics: list[Diagnostic] = []
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        kind = detail["type"]
        try:
            code = DiagnosticCode(kind)
        except ValueError:
            code = _ERROR_CODES.get(kind, DiagnosticCode.TYPE)
        location = tuple(
            part if isinstance(part, int) or part in _FIELDS else "<key>"
            for part in detail["loc"]
            if part not in _VARIANTS
        )
        if kind == "union_tag_not_found":
            location += ("type",)
        item = Diagnostic(code, location)
        if item not in diagnostics:
            diagnostics.append(item)
        if len(diagnostics) > 50:
            return tuple(diagnostics[:50]) + (Diagnostic(DiagnosticCode.TRUNCATED),)
    return tuple(diagnostics)
