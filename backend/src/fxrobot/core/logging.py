"""Structured logging with correlation IDs and secret masking.

Every record carries the current correlation ID so a single request (and,
later, a signal → risk decision → order → position chain) can be traced.
Values under sensitive keys are masked before they are ever formatted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fxrobot.core.config import LogFormat
from fxrobot.core.context import get_correlation_id

MASK = "***"

_SENSITIVE_KEY = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key",
    re.IGNORECASE,
)
# Masks `password=...`, `token: ...` style fragments inside free-text messages.
_SENSITIVE_INLINE = re.compile(
    r"(?P<key>pass(?:word|wd)?|secret|token|api[_-]?key|authorization)"
    r"(?P<sep>\s*[=:]\s*)(?P<value>[^\s,;&]+)",
    re.IGNORECASE,
)

# Attributes present on every LogRecord; anything else came from `extra=`.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def mask_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key):
        return MASK
    return mask_data(value)


def mask_data(value: Any) -> Any:
    """Recursively mask sensitive keys in mappings / sequences."""
    if isinstance(value, Mapping):
        return {str(k): mask_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_data(v) for v in value]
    if isinstance(value, str):
        return mask_text(value)
    return value


def mask_text(text: str) -> str:
    return _SENSITIVE_INLINE.sub(lambda m: f"{m['key']}{m['sep']}{MASK}", text)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: mask_value(key, value)
        for key, value in vars(record).items()
        if key not in _RESERVED and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_text(record.getMessage()),
            "correlation_id": get_correlation_id(),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S")
        cid = get_correlation_id()
        extras = " ".join(f"{k}={v}" for k, v in _extra_fields(record).items())
        line = f"{ts} {record.levelname:<8} {record.name}: {mask_text(record.getMessage())}"
        if extras:
            line += f"  {extras}"
        if cid:
            line += f"  [cid={cid[:12]}]"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(level: str, fmt: LogFormat) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt is LogFormat.JSON else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Route uvicorn through our formatter; drop its duplicate access log
    # (we emit our own request log with correlation IDs).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
