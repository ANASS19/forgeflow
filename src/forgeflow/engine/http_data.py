"""Bounded JSON response parsing and RFC 6901 lookup; no response data in errors."""

import json
import math
import re
from typing import cast

from pydantic import JsonValue

from forgeflow.domain import ErrorCode, ForgeFlowError

MAX_RESPONSE_BYTES = 1024 * 1024


def _pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _integer(value: str) -> int:
    if len(value) > 4096:
        raise ValueError("Integer budget exceeded.")
    return int(value)


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite number.")
    return number


def _constant(value: str) -> JsonValue:
    raise ValueError("Non-JSON numeric constant.")


def parse_response(body: bytes) -> JsonValue:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ForgeFlowError(ErrorCode.HTTP_SIZE)
    try:
        text = body.decode("utf-8-sig")
        depth = 0
        quoted = escaped = False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                if depth > 32:
                    raise ValueError("JSON depth budget exceeded.")
            elif character in "]}":
                depth -= 1
        return cast(
            JsonValue,
            json.loads(
                text,
                object_pairs_hook=_pairs,
                parse_int=_integer,
                parse_float=_float,
                parse_constant=_constant,
            ),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ForgeFlowError(ErrorCode.HTTP_JSON) from None


def json_pointer(document: JsonValue, pointer: str) -> JsonValue:
    current = document
    for segment in pointer[1:].split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            index = int(key)
            if index >= len(current):
                raise ForgeFlowError(ErrorCode.CAPTURE_MISSING)
            current = current[index]
        else:
            raise ForgeFlowError(ErrorCode.CAPTURE_MISSING)
    return current
