"""Bounded transient-failure delays; only numeric decisions are retained."""

import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    jitter = random.uniform(0, min(5.0, 0.5 * 2 ** (attempt - 1)))
    return max(jitter, min(30.0, max(0.0, retry_after or 0)))


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if value is None or len(value) > 128:
        return None
    text = value.strip()
    if text.isascii() and text.isdigit():
        return float(min(int(text), 30))
    try:
        date = parsedate_to_datetime(text)
        if date.tzinfo is None:
            return None
        seconds = (date.astimezone(UTC) - (now or datetime.now(UTC))).total_seconds()
        return min(30.0, max(0.0, seconds))
    except (ValueError, TypeError, OverflowError):
        return None
