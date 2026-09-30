"""Request-scoped context (correlation IDs) shared by logging and audit."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Accept caller-supplied IDs only if they are short and safe to log.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def sanitize_correlation_id(candidate: str | None) -> str:
    if candidate and _SAFE_ID.match(candidate):
        return candidate
    return new_correlation_id()


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)
