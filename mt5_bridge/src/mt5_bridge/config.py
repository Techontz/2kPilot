"""Bridge configuration (environment variables and optional ``.env`` file)."""

from __future__ import annotations

import ipaddress
from functools import cached_property

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- security -------------------------------------------------------
    bridge_secret: SecretStr = Field(..., description="Shared HMAC secret, >= 32 characters")
    bridge_allowed_ips: str = Field(
        default="", description="Comma-separated client IPs/CIDRs; empty allows any"
    )
    bridge_max_clock_skew_seconds: int = 30
    bridge_nonce_ttl_seconds: int = 120
    bridge_max_body_bytes: int = 64 * 1024

    # --- server -----------------------------------------------------------
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8710
    bridge_ssl_certfile: str | None = None
    bridge_ssl_keyfile: str | None = None
    bridge_log_level: str = "INFO"

    # --- MetaTrader 5 -----------------------------------------------------------
    mt5_terminal_path: str | None = None
    mt5_magic: int = 20250
    mt5_default_deviation_points: int = 20
    broker_server_utc_offset: str = "auto"
    broker_offset_symbols: str = "EURUSD,GBPUSD,USDJPY,EURJPY,XAUUSD"
    broker_offset_refresh_seconds: int = 3600

    # --- timeouts (seconds) -------------------------------------------------------
    read_timeout_seconds: float = 10.0
    trade_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 90.0

    # --- storage --------------------------------------------------------------------
    journal_path: str = "mt5_bridge_journal.sqlite3"

    @field_validator("bridge_secret")
    @classmethod
    def _secret_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("BRIDGE_SECRET must be at least 32 characters")
        return v

    @field_validator("broker_server_utc_offset")
    @classmethod
    def _offset_format(cls, v: str) -> str:
        v = v.strip()
        if v.lower() == "auto":
            return "auto"
        try:
            hours = float(v)
        except ValueError as exc:
            raise ValueError("BROKER_SERVER_UTC_OFFSET must be 'auto' or hours, e.g. +3") from exc
        if not -14 <= hours <= 14:
            raise ValueError("BROKER_SERVER_UTC_OFFSET out of range")
        return v

    @field_validator("bridge_allowed_ips")
    @classmethod
    def _ips_format(cls, v: str) -> str:
        for part in v.split(","):
            if part.strip():
                ipaddress.ip_network(part.strip(), strict=False)
        return v

    @property
    def secret_bytes(self) -> bytes:
        return self.bridge_secret.get_secret_value().encode("utf-8")

    @cached_property
    def allowed_networks(self) -> list[IPNetwork]:
        return [
            ipaddress.ip_network(p.strip(), strict=False)
            for p in self.bridge_allowed_ips.split(",")
            if p.strip()
        ]

    @property
    def fixed_offset_seconds(self) -> int | None:
        """The fixed server UTC offset in seconds, or ``None`` for auto-detection."""
        if self.broker_server_utc_offset == "auto":
            return None
        return round(float(self.broker_server_utc_offset) * 3600)

    @property
    def offset_symbols(self) -> list[str]:
        return [s.strip() for s in self.broker_offset_symbols.split(",") if s.strip()]
