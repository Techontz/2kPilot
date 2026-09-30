import pytest
from pydantic import ValidationError

from fxrobot.core.config import AppEnv, Settings


def test_production_requires_secure_cookies_and_encryption_key() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(_env_file=None, app_env=AppEnv.PRODUCTION, secret_encryption_key="k")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="SECRET_ENCRYPTION_KEY"):
        Settings(_env_file=None, app_env=AppEnv.PRODUCTION, cookie_secure=True)  # type: ignore[call-arg]


def test_live_trading_is_locked_by_default() -> None:
    assert Settings(_env_file=None).live_trading_enabled is False  # type: ignore[call-arg]


def test_cors_origins_parsed_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings(_env_file=None).cors_origins == ["http://a.test", "http://b.test"]  # type: ignore[call-arg]


def test_secret_key_is_not_revealed_in_repr() -> None:
    settings = Settings(_env_file=None, secret_encryption_key="super-secret")  # type: ignore[call-arg]
    assert "super-secret" not in repr(settings)
