"""Trading-engine configuration, loaded from environment variables / `.env`."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "2kFX trading engine"
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    # Same MySQL database as the Laravel backend (Laravel owns the schema).
    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/twokfx?charset=utf8mb4"
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)

    # Internal API (called only by Laravel). Bind to loopback.
    engine_host: str = "127.0.0.1"
    engine_port: int = 8431
    # Shared HMAC secret with Laravel (ENGINE_API_SECRET in backend/.env).
    engine_api_secret: SecretStr = SecretStr("")

    # AES-256-GCM key shared with Laravel (BROKER_CREDENTIALS_KEY).
    broker_credentials_key: SecretStr = SecretStr("")

    # Hard lock: while False no LIVE account can ever trade.
    live_trading_enabled: bool = False

    # Run the automated trading loop in this process.
    engine_enabled: bool = True
    engine_tick_seconds: float = Field(default=2.0, ge=0.2, le=60)

    # Deriv: App ID registered at developers.deriv.com (sent as Deriv-App-ID).
    deriv_app_id: str = ""
    deriv_api_url: str = "https://api.derivws.com"

    @field_validator("log_level")
    @classmethod
    def _normalise_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return level

    @model_validator(mode="after")
    def _enforce_safety(self) -> Settings:
        if self.app_env is AppEnv.PRODUCTION:
            problems = []
            if len(self.engine_api_secret.get_secret_value()) < 32:
                problems.append("ENGINE_API_SECRET must be at least 32 characters")
            if not self.broker_credentials_key.get_secret_value():
                problems.append("BROKER_CREDENTIALS_KEY must be set")
            if problems:
                raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
