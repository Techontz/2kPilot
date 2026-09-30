from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from fxrobot.domain.modes import TradingMode
from fxrobot.domain.trading import EngineState
from fxrobot.services.trading_control import TradingStatus


class TradingStatusOut(BaseModel):
    trading_mode: TradingMode
    kill_switch_engaged: bool
    kill_switch_reason: str | None
    kill_switch_changed_at: datetime | None
    mode_changed_at: datetime | None
    live_trading_locked: bool
    new_orders_permitted: bool
    engine_state: EngineState
    engine_detail: str

    @classmethod
    def from_status(cls, status: TradingStatus) -> TradingStatusOut:
        s = status.state
        return cls(
            trading_mode=s.trading_mode,
            kill_switch_engaged=s.kill_switch_engaged,
            kill_switch_reason=s.kill_switch_reason,
            kill_switch_changed_at=s.kill_switch_changed_at,
            mode_changed_at=s.mode_changed_at,
            live_trading_locked=status.live_trading_locked,
            new_orders_permitted=status.new_orders_permitted,
            engine_state=status.engine_state,
            engine_detail=status.engine_detail,
        )


class SystemStatusOut(BaseModel):
    app_name: str
    version: str
    environment: str
    trading: TradingStatusOut
    broker_accounts_connected: int = Field(description="Accounts whose connection is CONNECTED.")
    broker_accounts_total: int = Field(description="All saved trading accounts.")


class StopTradingRequest(BaseModel):
    reason: str = Field(default="Manual stop from dashboard", min_length=1, max_length=500)


class ResumeTradingRequest(BaseModel):
    confirm: Literal[True]


class SetModeRequest(BaseModel):
    mode: TradingMode
    password: str | None = Field(default=None, max_length=256)
    confirmation_phrase: str | None = Field(default=None, max_length=100)


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str] = Field(default_factory=dict)
