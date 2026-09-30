"""Shared fixtures. Tests run against a real PostgreSQL database
(TEST_DATABASE_URL, default: local `fxrobot_test`), migrated with Alembic —
so every run also verifies the migrations."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fxrobot.core.config import AppEnv, LogFormat, Settings
from fxrobot.core.crypto import generate_key
from fxrobot.main import create_app
from fxrobot.models import User, UserRole
from fxrobot.services import auth

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://localhost:5432/fxrobot_test"
)
BACKEND_DIR = Path(__file__).resolve().parents[1]
OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "Correct-Horse-42"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "database_url": TEST_DATABASE_URL,
        "secret_encryption_key": generate_key(),
        "log_format": LogFormat.JSON,
        "live_trading_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "src/fxrobot/db/migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_database(migrated_database: None) -> Iterator[None]:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        # system_state references users, so it is truncated too and re-seeded
        # exactly as the migration seeds it.
        conn.execute(
            text("TRUNCATE users, user_sessions, audit_logs, system_state RESTART IDENTITY CASCADE")
        )
        conn.execute(
            text(
                "INSERT INTO system_state "
                "(id, trading_mode, kill_switch_engaged, kill_switch_reason) "
                "VALUES (1, 'DEMO', true, 'Initial state')"
            )
        )
    engine.dispose()
    yield


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app_factory() -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(**overrides: object) -> TestClient:
        client = TestClient(create_app(make_settings(**overrides)))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(app_factory: Callable[..., TestClient]) -> TestClient:
    return app_factory()


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        yield session


def _create_user(db: Session, email: str, role: UserRole) -> User:
    user = auth.create_user(
        db, email=email, password=OWNER_PASSWORD, display_name=email.split("@")[0], role=role
    )
    db.commit()
    return user


@pytest.fixture
def owner(db: Session) -> User:
    return _create_user(db, OWNER_EMAIL, UserRole.OWNER)


@pytest.fixture
def viewer(db: Session) -> User:
    return _create_user(db, "viewer@example.com", UserRole.VIEWER)


def login(client: TestClient, email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD) -> str:
    """Log in and configure the client to send the CSRF header. Returns the CSRF token."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf = client.cookies["fx_csrf"]
    client.headers["X-CSRF-Token"] = csrf
    return csrf


@pytest.fixture
def owner_client(client: TestClient, owner: User) -> TestClient:
    login(client)
    return client
