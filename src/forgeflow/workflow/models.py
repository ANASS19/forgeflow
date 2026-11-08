"""Strict schema-v1 objects with local constraints and no cross-step analysis."""

import ipaddress
import math
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

from forgeflow.workflow.diagnostics import DiagnosticCode

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$", max_length=64)]
WorkflowName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)]
AttemptTimeout = Annotated[float, Field(gt=0, le=300)]


def _reject(code: DiagnosticCode) -> PydanticCustomError:
    # Messages are intentionally constant; the loading boundary substitutes public explanations.
    return PydanticCustomError(code.value, "The workflow field violates a structural constraint.")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
        validate_default=True,
    )


def _finite_json(value: JsonValue) -> JsonValue:
    if isinstance(value, float) and not math.isfinite(value):
        raise _reject(DiagnosticCode.YAML_NONFINITE)
    if isinstance(value, dict):
        for child in value.values():
            _finite_json(child)
    elif isinstance(value, list):
        for child in value:
            _finite_json(child)
    return value


class LiteralOperand(StrictModel):
    literal: JsonValue

    @field_validator("literal")
    @classmethod
    def finite_value(cls, value: JsonValue) -> JsonValue:
        return _finite_json(value)


class ReferenceOperand(StrictModel):
    ref: Annotated[
        str,
        StringConstraints(
            pattern=r"^[a-z][a-z0-9_]{0,63}\.outputs\.[a-z][a-z0-9_]{0,63}$", max_length=137
        ),
    ]


Operand = LiteralOperand | ReferenceOperand


class QueryLiteral(StrictModel):
    literal: str | int | float | bool


class HeaderLiteral(StrictModel):
    literal: Annotated[str, Field(max_length=8192)]

    @field_validator("literal")
    @classmethod
    def safe_text(cls, value: str) -> str:
        return _header_text(value)


class HeaderSecret(StrictModel):
    secret: Annotated[
        str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$", max_length=128)
    ]
    prefix: Annotated[str, Field(max_length=128)] = ""

    @field_validator("prefix")
    @classmethod
    def safe_prefix(cls, value: str) -> str:
        return _header_text(value)


def _header_text(value: str) -> str:
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise _reject(DiagnosticCode.HEADER)
    return value


_MANAGED_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "cookie",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "upgrade",
        "accept-encoding",
    }
)
_CREDENTIAL_HEADERS = frozenset(
    {"authorization", "x-api-key", "api-key", "x-auth-token", "x-access-token"}
)
_CREDENTIAL_QUERY = frozenset(
    {
        "token",
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "client_secret",
    }
)


class HttpRequest(StrictModel):
    method: Literal["GET", "HEAD"]
    url: Annotated[str, Field(min_length=1, max_length=8192)]
    query: Annotated[dict[str, QueryLiteral | ReferenceOperand], Field(max_length=100)] = Field(
        default_factory=dict
    )
    headers: Annotated[dict[str, HeaderLiteral | HeaderSecret], Field(max_length=100)] = Field(
        default_factory=dict
    )

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise _reject(DiagnosticCode.URL)
        if any(char in value for char in ("?", "#", "\\")):
            raise _reject(DiagnosticCode.URL)
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)
                or "%" in parsed.hostname
            ):
                raise _reject(DiagnosticCode.URL)
            parsed.hostname.encode("idna")
            if ":" in parsed.hostname:
                ipaddress.IPv6Address(parsed.hostname)
            elif not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in parsed.hostname.encode("idna")
                .decode("ascii")
                .removesuffix(".")
                .split(".")
            ):
                raise _reject(DiagnosticCode.URL)
        except (ValueError, UnicodeError):
            raise _reject(DiagnosticCode.URL) from None
        return value

    @field_validator("query")
    @classmethod
    def safe_query(
        cls, value: dict[str, QueryLiteral | ReferenceOperand]
    ) -> dict[str, QueryLiteral | ReferenceOperand]:
        for name in value:
            if (
                not name
                or len(name) > 256
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in name)
                or name.lower().replace("-", "_") in _CREDENTIAL_QUERY
            ):
                raise _reject(DiagnosticCode.QUERY)
        return value

    @field_validator("headers")
    @classmethod
    def safe_headers(
        cls, value: dict[str, HeaderLiteral | HeaderSecret]
    ) -> dict[str, HeaderLiteral | HeaderSecret]:
        seen: set[str] = set()
        for name, operand in value.items():
            normalized = name.lower()
            if (
                len(name) > 128
                or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or normalized in seen
                or normalized in _MANAGED_HEADERS
            ):
                raise _reject(DiagnosticCode.HEADER)
            if normalized in _CREDENTIAL_HEADERS and not isinstance(operand, HeaderSecret):
                raise _reject(DiagnosticCode.HEADER_SECRET)
            seen.add(normalized)
        return value


class ExecutionConfig(StrictModel):
    concurrency: Annotated[int, Field(ge=1, le=16)] = 4
    timeout_seconds: Annotated[float, Field(ge=1, le=3600)] = 300


class WorkflowDefaults(StrictModel):
    attempt_timeout_seconds: AttemptTimeout = 30


class RetryPolicy(StrictModel):
    max_attempts: Annotated[int, Field(ge=1, le=5)] = 1


class StepBase(StrictModel):
    id: Identifier
    needs: Annotated[list[Identifier], Field(max_length=100)] = Field(default_factory=list)
    attempt_timeout_seconds: AttemptTimeout | None = Field(default=None, validate_default=False)

    @field_validator("attempt_timeout_seconds", mode="before")
    @classmethod
    def explicit_timeout_is_numeric(cls, value: object) -> object:
        if value is None:
            raise _reject(DiagnosticCode.TYPE)
        return value

    @field_validator("needs")
    @classmethod
    def unique_needs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise _reject(DiagnosticCode.NEEDS_DUPLICATE)
        return value


class ValueStep(StepBase):
    type: Literal["value"]
    values: Annotated[dict[Identifier, JsonValue], Field(min_length=1, max_length=100)]

    @field_validator("values")
    @classmethod
    def finite_values(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        for child in value.values():
            _finite_json(child)
        return value


class HttpStep(StepBase):
    type: Literal["http"]
    request: HttpRequest
    expect_status: Annotated[
        list[Annotated[int, Field(ge=100, le=599)]], Field(min_length=1, max_length=500)
    ] = Field(default_factory=lambda: list(range(200, 300)))
    capture: Annotated[dict[Identifier, str], Field(max_length=100)] = Field(default_factory=dict)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @field_validator("capture")
    @classmethod
    def valid_captures(cls, value: dict[str, str], info: ValidationInfo) -> dict[str, str]:
        request = info.data.get("request")
        if value and isinstance(request, HttpRequest) and request.method == "HEAD":
            raise _reject(DiagnosticCode.HEAD_CAPTURE)
        for name, pointer in value.items():
            if (
                name == "status_code"
                or not pointer.startswith("/")
                or len(pointer) > 1024
                or re.search(r"~(?![01])", pointer)
            ):
                raise _reject(DiagnosticCode.CAPTURE)
        return value


class AssertStep(StepBase):
    type: Literal["assert"]
    left: Operand
    op: Literal["eq"]
    right: Operand


Step = Annotated[ValueStep | HttpStep | AssertStep, Field(discriminator="type")]


class Workflow(StrictModel):
    schema_version: Literal[1]
    name: WorkflowName
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    steps: Annotated[list[Step], Field(min_length=1, max_length=100)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def supported_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise _reject(DiagnosticCode.VERSION)
        return value

    @field_validator("steps")
    @classmethod
    def unique_steps(
        cls, value: list[ValueStep | HttpStep | AssertStep]
    ) -> list[ValueStep | HttpStep | AssertStep]:
        if len(value) != len({step.id for step in value}):
            raise _reject(DiagnosticCode.STEP_DUPLICATE)
        return value
