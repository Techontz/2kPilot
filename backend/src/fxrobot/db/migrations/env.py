from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool

import fxrobot.models  # noqa: F401  (registers every model on Base.metadata)
from fxrobot.core.config import get_settings
from fxrobot.db.base import Base
from fxrobot.db.session import build_engine
from fxrobot.db.types import UTCDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # Tests pass an explicit URL via config attributes; otherwise use settings.
    return config.attributes.get("database_url") or get_settings().database_url


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    # Keep generated migrations independent of application code.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "DT"
    return False


COMMON = {"target_metadata": target_metadata, "compare_type": True, "render_item": render_item}


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, **COMMON)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, **COMMON)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
