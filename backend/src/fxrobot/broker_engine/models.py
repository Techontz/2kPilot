"""Broker-neutral data transfer objects.

Prices and money use `Decimal` to avoid binary floating-point drift. All
timestamps are timezone-aware UTC. Adapters convert broker-native values
into these types at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from fxrobot.domain.modes import AccountEnvironment


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def seconds(self) -> int:
        return _TIMEFRAME_SECONDS[self]


_TIMEFRAME_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
    Timeframe.W1: 604800,
}


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(StrEnum):
    PENDING = "PENDING"  # resting order at the broker
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"  # outcome not confirmed — requires reconciliation


@dataclass(frozen=True, slots=True)
class AccountInfo:
    account_id: str  # broker login / account number
    name: str
    server: str
    currency: str
    environment: AccountEnvironment
    balance: Decimal
    equity: Decimal
    margin: Decimal | None = None
    free_margin: Decimal | None = None
    margin_level: Decimal | None = None  # percent
    leverage: int | None = None
    trade_allowed: bool = False


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    name: str  # broker symbol, e.g. "EURUSD" or "EURUSD.m"
    description: str
    base_currency: str
    quote_currency: str
    digits: int
    point: Decimal  # smallest price increment
    contract_size: Decimal  # units per 1.00 lot
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    trade_allowed: bool

    @property
    def pip_size(self) -> Decimal:
        # 5/3-digit quotes use fractional pips: 1 pip = 10 points.
        return self.point * 10 if self.digits in (3, 5) else self.point


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    time: datetime

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime  # bar open time, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int
    spread_points: int | None = None


@dataclass(frozen=True, slots=True)
class Position:
    position_id: str
    symbol: str
    side: Side
    volume: Decimal
    open_price: Decimal
    open_time: datetime
    stop_loss: Decimal | None
    take_profit: Decimal | None
    unrealized_pnl: Decimal
    swap: Decimal = Decimal(0)
    client_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    volume: Decimal
    status: OrderStatus
    price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    created_time: datetime
    client_order_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An order instruction. Produced by the execution engine, never by strategies."""

    client_order_id: str  # idempotency key; adapters must pass it to the broker
    symbol: str
    side: Side
    order_type: OrderType
    volume: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    price: Decimal | None = None  # required for LIMIT / STOP
    max_slippage_points: int | None = None
    comment: str = ""

    def __post_init__(self) -> None:
        if self.volume <= 0:
            raise ValueError("volume must be positive")
        if self.order_type is not OrderType.MARKET and self.price is None:
            raise ValueError(f"{self.order_type} orders require a price")


@dataclass(frozen=True, slots=True)
class OrderModification:
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderResult:
    client_order_id: str
    status: OrderStatus
    broker_order_id: str | None = None
    filled_volume: Decimal = Decimal(0)
    fill_price: Decimal | None = None
    broker_message: str | None = None
    raw: dict[str, str] = field(default_factory=dict)
