"""Signal → order → trade lifecycle, plus the journal event log."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import NOW_DEFAULT, Money, Price, Volume, str_enum, utcnow
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.trading import (
    ExitReason,
    OrderPurpose,
    OrderStatus,
    OrderType,
    SignalSource,
    SignalStatus,
    TradeStatus,
)


class Signal(Base):
    """A strategy's trade intention and the risk engine's decision about it."""

    __tablename__ = "signals"
    __table_args__ = (
        # Duplicate-signal protection: one signal per assignment, bar and direction.
        UniqueConstraint("assignment_id", "bar_time", "side", name="uq_signals_dedupe"),
        Index("ix_signals_account_created", "account_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[SignalSource] = mapped_column(
        str_enum(SignalSource, "signal_source", 16), default=SignalSource.STRATEGY
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_assignments.id", ondelete="SET NULL")
    )
    # NULL only for MANUAL tickets (enforced by a CHECK constraint).
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Manual tickets: one key per confirmation, so a retry never opens a second position.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[Side] = mapped_column(str_enum(Side, "side", 8))
    timeframe: Mapped[Timeframe] = mapped_column(str_enum(Timeframe, "signal_timeframe", 8))
    bar_time: Mapped[datetime]
    entry_type: Mapped[OrderType] = mapped_column(str_enum(OrderType, "signal_entry_type", 16))
    entry_price: Mapped[Decimal] = mapped_column(Price())
    stop_loss: Mapped[Decimal] = mapped_column(Price())
    take_profit: Mapped[Decimal | None] = mapped_column(Price())
    reasons: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[SignalStatus] = mapped_column(
        str_enum(SignalStatus, "signal_status", 16), default=SignalStatus.NEW
    )
    # Every rule's outcome, e.g. [{"rule": "daily_loss", "passed": false, "detail": "..."}]
    risk_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    requested_volume: Mapped[Decimal | None] = mapped_column(Volume())
    volume: Mapped[Decimal | None] = mapped_column(Volume())
    risk_amount: Mapped[Decimal | None] = mapped_column(Money())
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    decided_at: Mapped[datetime | None]


class Order(TimestampMixin, Base):
    """Every instruction sent (or about to be sent) to a broker.

    `client_order_id` is the idempotency key: it is persisted BEFORE the broker
    call, sent to the broker, and used to reconcile uncertain outcomes.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_account_created", "account_id", "created_at"),
        Index("ix_orders_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    client_order_id: Mapped[str] = mapped_column(String(32), unique=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id", ondelete="SET NULL"))
    purpose: Mapped[OrderPurpose] = mapped_column(str_enum(OrderPurpose, "order_purpose", 8))
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[Side] = mapped_column(str_enum(Side, "order_side", 8))
    order_type: Mapped[OrderType] = mapped_column(str_enum(OrderType, "order_type", 16))
    volume: Mapped[Decimal] = mapped_column(Volume())
    filled_volume: Mapped[Decimal] = mapped_column(Volume(), default=Decimal(0))
    requested_price: Mapped[Decimal | None] = mapped_column(Price())
    fill_price: Mapped[Decimal | None] = mapped_column(Price())
    stop_loss: Mapped[Decimal | None] = mapped_column(Price())
    take_profit: Mapped[Decimal | None] = mapped_column(Price())
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, "order_status", 20), default=OrderStatus.PENDING_SUBMIT
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    broker_position_id: Mapped[str | None] = mapped_column(String(64))
    broker_code: Mapped[str | None] = mapped_column(String(64))
    broker_message: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(default=0)
    is_simulated: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    submitted_at: Mapped[datetime | None]
    filled_at: Mapped[datetime | None]
    last_reconciled_at: Mapped[datetime | None]


class Trade(TimestampMixin, Base):
    """A position from open to close — the unit of the journal and analytics."""

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_account_status", "account_id", "status"),
        Index("ix_trades_account_exit", "account_id", "exit_time"),
        UniqueConstraint("account_id", "broker_position_id", name="uq_trades_broker_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="SET NULL")
    )
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[Side] = mapped_column(str_enum(Side, "trade_side", 8))
    status: Mapped[TradeStatus] = mapped_column(
        str_enum(TradeStatus, "trade_status", 8), default=TradeStatus.OPEN
    )
    volume: Mapped[Decimal] = mapped_column(Volume())
    requested_entry: Mapped[Decimal | None] = mapped_column(Price())
    entry_price: Mapped[Decimal] = mapped_column(Price())
    entry_time: Mapped[datetime]
    stop_loss: Mapped[Decimal | None] = mapped_column(Price())
    take_profit: Mapped[Decimal | None] = mapped_column(Price())
    initial_stop_loss: Mapped[Decimal | None] = mapped_column(Price())
    risk_amount: Mapped[Decimal | None] = mapped_column(Money())
    spread_at_entry: Mapped[Decimal | None] = mapped_column(Price())
    slippage_pips: Mapped[Decimal | None] = mapped_column(Price())
    session: Mapped[str | None] = mapped_column(String(20))
    broker_position_id: Mapped[str | None] = mapped_column(String(64))
    exit_price: Mapped[Decimal | None] = mapped_column(Price())
    exit_time: Mapped[datetime | None]
    exit_reason: Mapped[ExitReason | None] = mapped_column(str_enum(ExitReason, "exit_reason", 16))
    gross_pnl: Mapped[Decimal | None] = mapped_column(Money())
    commission: Mapped[Decimal] = mapped_column(Money(), default=Decimal(0))
    swap: Mapped[Decimal] = mapped_column(Money(), default=Decimal(0))
    net_pnl: Mapped[Decimal | None] = mapped_column(Money())
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Money())
    r_multiple: Mapped[Decimal | None] = mapped_column(Price())
    is_simulated: Mapped[bool] = mapped_column(default=False, server_default=text("0"))


class TradeEvent(Base):
    """The journal: an append-only timeline of every lifecycle step."""

    __tablename__ = "trade_events"
    __table_args__ = (
        Index("ix_trade_events_account_time", "account_id", "occurred_at"),
        Index("ix_trade_events_trade", "trade_id"),
        Index("ix_trade_events_signal", "signal_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    trade_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trades.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
