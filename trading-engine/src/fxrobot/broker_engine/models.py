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

from fxrobot.domain.contracts import ContractFill, ContractOrder, ContractType
from fxrobot.domain.market import Candle, Quote, Side, SymbolInfo, Timeframe
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import OrderStatus, OrderType

__all__ = [
    "AccountInfo",
    "BrokerCapabilities",
    "BrokerHealth",
    "Candle",
    "Deal",
    "DealEntry",
    "Order",
    "OrderHint",
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
    # Contracts only (None for SPOT positions).
    contract_type: ContractType | None = None
    stake: Decimal | None = None
    payout: Decimal | None = None
    multiplier: int | None = None
    expires_at: datetime | None = None
    is_valid_to_sell: bool | None = None


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
    reason: str = "OTHER"  # SL | TP | SO | CLIENT | EXPERT | EXPIRY | OTHER
    # Contracts: how it settled (WON | LOST | SOLD | CANCELLED) and its payout.
    outcome: str | None = None
    payout: Decimal | None = None
    contract_type: str | None = None


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
    # Set for contract trades (Rise/Fall, Multipliers): what to buy and the stake.
    # `volume` is then 1 (one contract); lots do not apply.
    contract: ContractOrder | None = None

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
    contract: ContractFill | None = None  # contract trades: what the broker sold us


@dataclass(frozen=True, slots=True)
class BrokerHealth:
    connected: bool
    detail: str
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class OrderHint:
    """What we sent, for brokers that cannot store our client order id (Deriv).

    Reconciliation passes it to `find_order_by_client_id` so the adapter can
    match a broker-side contract to our order after a timeout or restart. A
    lookup that cannot read the broker's state must RAISE (BrokerError), never
    answer "not found": "not found" lets the engine conclude "not executed".
    """

    symbol: str
    side: Side
    volume: Decimal
    submitted_at: datetime | None
    contract_type: ContractType | None = None  # contracts: the exact type that was bought
    stake: Decimal | None = None  # contracts: the stake we asked to pay
    # Broker ids the database already ties to OTHER orders/trades of this account:
    # never matched again (the adapter's in-memory claims are lost on restart).
    claimed_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class BrokerCapabilities:
    """What a broker supports. Stored on the account and shown in the UI, so a
    feature the broker does not offer is never presented as available."""

    market_orders: bool = True
    pending_orders: bool = True
    modify_position: bool = True
    partial_close: bool = True
    historical_candles: bool = True
    trade_history: bool = True
    client_order_ids: bool = True  # broker stores our idempotency key
    volume_unit: str = "lots"  # "lots" | "units" | "stake"
    # Contract families offered: "SPOT" (lots), "RISE_FALL", "MULTIPLIER".
    contract_families: tuple[str, ...] = ("SPOT",)
    notes: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {
            "market_orders": self.market_orders,
            "pending_orders": self.pending_orders,
            "modify_position": self.modify_position,
            "partial_close": self.partial_close,
            "historical_candles": self.historical_candles,
            "trade_history": self.trade_history,
            "client_order_ids": self.client_order_ids,
            "volume_unit": self.volume_unit,
            "contract_families": list(self.contract_families),
            "notes": list(self.notes),
        }
