"""Shared fixtures.

Tests run against a real MySQL 8 database (TEST_DATABASE_URL, default:
`tradepilot_engine_test` on 127.0.0.1:3308) whose schema is created by the
**Laravel migrations** in ../backend — the same schema production uses. So
every engine test run also proves the engine and Laravel agree on the schema.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from fxrobot.broker_engine.adapters.paper_market import set_paper_clock
from fxrobot.core.config import AppEnv, LogFormat, Settings
from fxrobot.core.crypto import SecretBox, generate_key
from fxrobot.db.base import Base
from fxrobot.db.session import build_engine
from fxrobot.internal.auth import sign
from fxrobot.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+pymysql://root@127.0.0.1:3308/tradepilot_engine_test?charset=utf8mb4",
)
ENGINE_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ENGINE_DIR.parent / "backend"
ENGINE_SECRET = "test-engine-secret-0123456789-abcdefghijklmnop"
CREDENTIALS_KEY = generate_key()
OWNER_EMAIL = "owner@example.com"
# "Today" as paper markets see it in tests (a Wednesday, FX market open), so no
# test depends on the real date: where a simulation starts, which weekday it
# lands on and how far it may run are all fixed.
PAPER_NOW = datetime(2026, 3, 4, 14, 0, tzinfo=UTC)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "database_url": TEST_DATABASE_URL,
        "broker_credentials_key": CREDENTIALS_KEY,
        "engine_api_secret": ENGINE_SECRET,
        "log_format": LogFormat.JSON,
        "live_trading_enabled": False,
        "engine_enabled": False,  # tests drive the engine explicitly
        "deriv_app_id": "app-test",
        "anthropic_api_key": "",  # AI drafting off unless a test turns it on (never a real key)
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def secret_box() -> SecretBox:
    return SecretBox(CREDENTIALS_KEY)


def _ensure_database_exists() -> None:
    url = make_url(TEST_DATABASE_URL)
    server = create_engine(url.set(database=""), poolclass=NullPool)
    with server.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )
    server.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema with `php artisan migrate:fresh` (Laravel owns it)."""
    _ensure_database_exists()
    url = make_url(TEST_DATABASE_URL)
    env = {
        **os.environ,
        "APP_ENV": "testing",
        "DB_CONNECTION": "mysql",
        "DB_HOST": url.host or "127.0.0.1",
        "DB_PORT": str(url.port or 3306),
        "DB_DATABASE": url.database or "",
        "DB_USERNAME": url.username or "root",
        "DB_PASSWORD": url.password or "",
    }
    result = subprocess.run(
        ["php", "artisan", "migrate:fresh", "--force", "--no-interaction"],  # noqa: S607
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Laravel migrations failed:\n{result.stdout}\n{result.stderr}")


_TABLES = [t.name for t in Base.metadata.sorted_tables if t.name not in ("audit_logs", "users")]


@pytest.fixture(autouse=True)
def paper_now() -> Iterator[datetime]:
    """Pin the paper markets' clock (see PAPER_NOW)."""
    set_paper_clock(lambda: PAPER_NOW)
    yield PAPER_NOW
    set_paper_clock(None)


@pytest.fixture(autouse=True)
def clean_database(migrated_database: None) -> Iterator[None]:
    engine = build_engine(TEST_DATABASE_URL, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in [*_TABLES, "users"]:
            conn.execute(text(f"DELETE FROM `{table}`"))  # noqa: S608 (names from ORM metadata)
        conn.execute(text("TRUNCATE TABLE audit_logs"))  # append-only: TRUNCATE bypasses triggers
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.execute(text("INSERT INTO system_state (id, kill_switch_engaged) VALUES (1, false)"))
    engine.dispose()
    yield


@pytest.fixture
def settings() -> Settings:
    return make_settings()


class SignedClient(TestClient):
    """A TestClient that signs requests exactly like Laravel's EngineClient."""

    secret = ENGINE_SECRET

    def request(self, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        import json as jsonlib
        import secrets as pysecrets
        import time

        body = b""
        headers = dict(kwargs.get("headers") or {})
        kwargs["headers"] = headers
        if kwargs.get("json") is not None:
            body = jsonlib.dumps(kwargs.pop("json")).encode()
            kwargs["content"] = body
            headers["Content-Type"] = "application/json"
        else:
            kwargs.pop("json", None)
            if kwargs.get("content") is not None:
                content = kwargs["content"]
                body = content if isinstance(content, bytes) else content.encode()
        path = str(url)
        if kwargs.get("params"):
            from urllib.parse import urlencode

            path += "?" + urlencode(kwargs.pop("params"))
        timestamp = str(int(time.time()))
        nonce = pysecrets.token_hex(16)
        headers.update(
            {
                "X-Engine-Timestamp": timestamp,
                "X-Engine-Nonce": nonce,
                "X-Engine-Signature": sign(self.secret, method, path, timestamp, nonce, body),
            }
        )
        return super().request(method, path, *args, **kwargs)


@pytest.fixture
def app_factory() -> Iterator[Callable[..., SignedClient]]:
    clients: list[SignedClient] = []

    def factory(**overrides: object) -> SignedClient:
        client = SignedClient(create_app(make_settings(**overrides)))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(app_factory: Callable[..., SignedClient]) -> SignedClient:
    return app_factory()


@pytest.fixture
def db(client: SignedClient) -> Iterator[Session]:
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        yield session


@pytest.fixture
def owner(db: Session) -> uuid.UUID:
    """The default test user (the owner of factory-made accounts), as Laravel creates it."""
    from tests import factories

    return factories.ensure_user(db)


def fresh_heartbeat(db: Session) -> None:
    """Pretend a trading engine is alive."""
    db.execute(
        text(
            "UPDATE system_state SET engine_heartbeat_at = UTC_TIMESTAMP(6), "
            "engine_degraded = 0 WHERE id = 1"
        )
    )
    db.commit()
