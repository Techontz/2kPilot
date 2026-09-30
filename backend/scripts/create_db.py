"""Create the database named in DATABASE_URL if it does not exist (utf8mb4)."""

from __future__ import annotations

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from fxrobot.core.config import get_settings


def main() -> int:
    url = make_url(get_settings().database_url)
    server = create_engine(url.set(database=""), poolclass=NullPool)
    with server.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )
    server.dispose()
    print(f"Database `{url.database}` is ready on {url.host}:{url.port or 3306}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
