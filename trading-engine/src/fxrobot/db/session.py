from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from fxrobot.core.config import Settings

# Strict mode turns silent truncation/zero-dates into errors — essential for money.
MYSQL_SESSION_SQL = (
    "SET SESSION time_zone = '+00:00', "
    "sql_mode = 'STRICT_ALL_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
    "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY'"
)


def _configure_mysql_session(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute(MYSQL_SESSION_SQL)
    cursor.close()


def build_engine(url: str | Settings, **overrides: Any) -> Engine:
    settings = url if isinstance(url, Settings) else None
    database_url = settings.database_url if settings else str(url)
    options: dict[str, Any] = {
        "pool_pre_ping": True,  # survive dropped connections after DB restarts
        "pool_recycle": 1800,  # below MySQL's default wait_timeout
        "pool_timeout": 10,
        # READ COMMITTED: long-running loops (the trading engine) always see
        # fresh rows instead of a REPEATABLE READ snapshot.
        "isolation_level": "READ COMMITTED",
    }
    if settings:
        options["pool_size"] = settings.db_pool_size
        options["max_overflow"] = settings.db_max_overflow
    options.update(overrides)
    if options.get("poolclass") is not None:  # e.g. NullPool: no pool sizing options
        for key in ("pool_timeout", "pool_recycle", "pool_size", "max_overflow"):
            options.pop(key, None)
    engine = create_engine(database_url, **options)
    if engine.dialect.name == "mysql":
        event.listen(engine, "connect", _configure_mysql_session)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
