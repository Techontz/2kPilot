"""Request models. Responses are plain dicts built in :mod:`mt5_bridge.mapping`."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

CLIENT_ORDER_ID_PATTERN = r"^[a-z0-9]{8,24}$"
SYMBOL_PATTERN = r"^[A-Za-z0-9._#+\-]{1,32}$"
TICKET_PATTERN = r"^[0-9]{1,20}$"

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "STOP"]
Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _positive(v: Decimal | None, name: str) -> Decimal | None:
    if v is not None and (not v.is_finite() or v <= 0):
        raise ValueError(f"{name} must be a positive decimal")
    return v


class ConnectRequest(_Strict):
    login: str = Field(pattern=r"^[0-9]{1,20}$")
    password: SecretStr
    server: str = Field(min_length=1, max_length=128)
    terminal_path: str | None = None


class OrderRequest(_Strict):
    client_order_id: str = Field(pattern=CLIENT_ORDER_ID_PATTERN)
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    side: Side
    order_type: OrderType
    volume: Decimal
    price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    max_slippage_points: int = Field(default=20, ge=0, le=100_000)
    comment: str = Field(default="", max_length=64)

    @field_validator("volume")
    @classmethod
    def _vol(cls, v: Decimal) -> Decimal:
        _positive(v, "volume")
        return v

    @field_validator("price", "stop_loss", "take_profit")
    @classmethod
    def _prices(cls, v: Decimal | None) -> Decimal | None:
        return _positive(v, "price")

    @model_validator(mode="after")
    def _price_required(self) -> OrderRequest:
        if self.order_type != "MARKET" and self.price is None:
            raise ValueError("price is required for LIMIT and STOP orders")
        return self


class ModifyOrderRequest(_Strict):
    """Absent field → keep the current value. ``stop_loss``/``take_profit`` null → remove."""

    price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    @field_validator("price", "stop_loss", "take_profit")
    @classmethod
    def _prices(cls, v: Decimal | None) -> Decimal | None:
        return _positive(v, "price")


class ModifyPositionRequest(_Strict):
    """Absent field → keep the current value; null → remove."""

    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def _prices(cls, v: Decimal | None) -> Decimal | None:
        return _positive(v, "price")


class ClosePositionRequest(_Strict):
    client_order_id: str = Field(pattern=CLIENT_ORDER_ID_PATTERN)
    volume: Decimal | None = None
    max_slippage_points: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("volume")
    @classmethod
    def _vol(cls, v: Decimal | None) -> Decimal | None:
        return _positive(v, "volume")
