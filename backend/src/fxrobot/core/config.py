"""Typed application configuration loaded from environment variables / `.env`."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    app_name: str = "2kFX ROBOT"
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    database_url: str = "mysql+pymysql://root@127.0.0.1:3306/fxrobot?charset=utf8mb4"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=5, ge=0)

    # Fernet key for encrypting broker credentials at rest.
    secret_encryption_key: SecretStr = SecretStr("")

    cookie_secure: bool = False
    session_ttl_minutes: int = Field(default=720, ge=5)
    session_idle_timeout_minutes: int = Field(default=60, ge=5)

    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=900, ge=1)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Peers allowed to set X-Forwarded-For (the Next.js server that proxies the API).
    trusted_proxies: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"]
    )

    # Hard lock: while False the system can never enter LIVE mode.
    live_trading_enabled: bool = False

    @field_validator("cors_origins", "trusted_proxies", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return level

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Settings:
        if self.app_env is AppEnv.PRODUCTION:
            problems = []
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true")
            if not self.secret_encryption_key.get_secret_value():
                problems.append("SECRET_ENCRYPTION_KEY must be set")
            if problems:
                raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
