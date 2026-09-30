import io

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot import cli
from fxrobot.core import config
from fxrobot.models import User
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def _cli_uses_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config.get_settings.cache_clear()


def test_create_user_from_stdin(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Strong-Passw0rd\n"))
    code = cli.main(
        ["create-user", "--email", "Ops@Example.com", "--name", "Ops", "--password-stdin"]
    )
    assert code == 0
    user = db.scalars(select(User)).one()
    assert user.email == "ops@example.com"
    assert "Strong-Passw0rd" not in user.password_hash


def test_create_user_rejects_weak_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("weak\n"))
    code = cli.main(["create-user", "--email", "a@b.co", "--name", "A", "--password-stdin"])
    assert code == 1


def test_generate_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["generate-key"]) == 0
    assert len(capsys.readouterr().out.strip()) == 44
