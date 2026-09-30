"""Broker-neutral data transfer objects.

Market types (Timeframe, SymbolInfo, Quote, Candle, Side) live in
`fxrobot.domain.market` so strategies can use them without importing the
broker layer; they are re-exported here for adapters' convenience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from fxrobot.domain.market import Candle, Quote, Side, SymbolInfo, Timeframe
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import OrderStatus, OrderType

__all__ = [
    "AccountInfo",
    "BrokerHealth",
    "Candle",
    "Deal",
    "DealEntry",
    "Order",
    "OrderModification",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Position",
    "Quote",
    "Side",
    "SymbolInfo",
    "Timeframe",
]


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


class DealEntry(StrEnum):
    IN = "IN"
    OUT = "OUT"
    INOUT = "INOUT"


@dataclass(frozen=True, slots=True)
class Deal:
    """An execution in the broker's trade history."""

    deal_id: str
    order_id: str | None
    position_id: str | None
    symbol: str
    side: Side
    entry: DealEntry
    volume: Decimal
    price: Decimal
    time: datetime
    profit: Decimal
    commission: Decimal = Decimal(0)
    swap: Decimal = Decimal(0)
    fee: Decimal = Decimal(0)
    client_order_id: str | None = None
    reason: str = "OTHER"  # SL | TP | SO | CLIENT | EXPERT | OTHER


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
    client_order_id: str | None
    status: OrderStatus
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    filled_volume: Decimal = Decimal(0)
    fill_price: Decimal | None = None
    broker_code: str | None = None
    broker_message: str | None = None
    time: datetime | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrokerHealth:
    connected: bool
    detail: str
    latency_ms: float | None = None
