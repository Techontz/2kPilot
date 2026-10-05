"""Column types matching the MySQL schema created by Laravel's migrations.

The schema itself is owned by `backend/database/migrations`; these types only
describe how Python reads and writes it:

* timestamps are naive UTC DATETIME(6), returned as aware UTC datetimes
  (each connection sets `time_zone = '+00:00'`, see session.py);
* UUID primary/foreign keys are CHAR(36) strings with dashes;
* money and prices are DECIMAL, never floats.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import CHAR, Dialect, Enum, Numeric, text
from sqlalchemy.dialects import mysql
from sqlalchemy.types import DateTime, TypeDecorator, TypeEngine

# DATETIME(6) default; precision must match the column's fractional seconds.
NOW_DEFAULT = text("CURRENT_TIMESTAMP(6)")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "mysql":
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use timezone-aware UTC")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "mysql" else value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class UUID36(TypeDecorator[uuid.UUID]):
    """UUIDs stored as CHAR(36) with dashes — the format Laravel's schema uses."""

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))

    def process_result_value(self, value: str | None, dialect: Dialect) -> uuid.UUID | None:
        return None if value is None else uuid.UUID(value)


def str_enum(enum_cls: type[StrEnum], name: str, length: int = 24) -> Enum:
    """VARCHAR + CHECK instead of a native ENUM: portable and easy to extend."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


# Precision choices: prices cover JPY (3dp) to 5dp FX plus headroom;
# money in account currency; volumes in lots.
def Price() -> Numeric[Decimal]:  # noqa: N802
    return Numeric(24, 10, asdecimal=True)


def Money() -> Numeric[Decimal]:  # noqa: N802
    return Numeric(20, 6, asdecimal=True)


def Volume() -> Numeric[Decimal]:  # noqa: N802
    return Numeric(16, 4, asdecimal=True)
