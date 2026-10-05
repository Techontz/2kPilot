import pytest
from pydantic import ValidationError

from fxrobot.core.config import AppEnv, Settings


def test_production_requires_engine_secret_and_credentials_key() -> None:
    key = "base64:" + "A" * 43 + "="
    with pytest.raises(ValidationError, match="ENGINE_API_SECRET"):
        Settings(_env_file=None, app_env=AppEnv.PRODUCTION, broker_credentials_key=key)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="BROKER_CREDENTIALS_KEY"):
        Settings(_env_file=None, app_env=AppEnv.PRODUCTION, engine_api_secret="x" * 40)  # type: ignore[call-arg]


def test_live_trading_is_locked_by_default() -> None:
    assert Settings(_env_file=None).live_trading_enabled is False  # type: ignore[call-arg]


def test_engine_binds_to_loopback_by_default() -> None:
    assert Settings(_env_file=None).engine_host == "127.0.0.1"  # type: ignore[call-arg]


def test_secrets_are_not_revealed_in_repr() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        broker_credentials_key="super-secret-key",
        engine_api_secret="super-secret-hmac",
    )
    assert "super-secret" not in repr(settings)
