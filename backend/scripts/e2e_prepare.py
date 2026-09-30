"""Create a fresh, disposable database + verification user for browser E2E tests.

Usage: E2E_DATABASE_URL=mysql+pymysql://root@127.0.0.1:3308/fxrobot_e2e python scripts/e2e_prepare.py
The database named in the URL is DROPPED and recreated — never point it at real data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from fxrobot.db.session import build_engine, build_session_factory
from fxrobot.models import UserRole
from fxrobot.services import auth

URL = os.environ.get("E2E_DATABASE_URL", "mysql+pymysql://root@127.0.0.1:3308/fxrobot_e2e?charset=utf8mb4")
EMAIL = os.environ.get("E2E_EMAIL", "e2e@2kfx.local")
PASSWORD = os.environ.get("E2E_PASSWORD", "E2e-Verify-Passw0rd")


def main() -> int:
    url = make_url(URL)
    if not (url.database or "").endswith(("_e2e", "_e2e_test")):
        print("Refusing: the E2E database name must end with _e2e", file=sys.stderr)
        return 1
    server = create_engine(url.set(database=""), poolclass=NullPool)
    with server.begin() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
        conn.execute(text(f"CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"))
    server.dispose()
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "src/fxrobot/db/migrations"))
    cfg.attributes["database_url"] = URL
    command.upgrade(cfg, "head")
    engine = build_engine(URL, poolclass=NullPool)
    with build_session_factory(engine)() as db:
        auth.create_user(db, email=EMAIL, password=PASSWORD, display_name="E2E Owner", role=UserRole.OWNER)
        db.commit()
    engine.dispose()
    print(f"E2E database ready: {url.database}, user {EMAIL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
