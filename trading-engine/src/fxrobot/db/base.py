from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fxrobot.db.types import NOW_DEFAULT, UUID36, UTCDateTime, utcnow

# Deterministic constraint names (the schema itself is created by Laravel).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UTCDateTime(), uuid.UUID: UUID36()}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=NOW_DEFAULT
    )
