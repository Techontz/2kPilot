from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base
from fxrobot.db.types import NOW_DEFAULT, Money, Price, Volume, str_enum, utcnow
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.trading import BacktestKind, BacktestStatus, ExitReason


class Backtest(Base):
    """A reproducible simulation run: config, data identity, and results."""

    __tablename__ = "backtests"
    __table_args__ = (Index("ix_backtests_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("backtests.id", ondelete="CASCADE")
    )
    kind: Mapped[BacktestKind] = mapped_column(str_enum(BacktestKind, "backtest_kind", 24))
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[BacktestStatus] = mapped_column(
        str_enum(BacktestStatus, "backtest_status", 16), default=BacktestStatus.QUEUED
    )
    strategy_key: Mapped[str] = mapped_column(String(60))
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="SET NULL")
    )
    code_version: Mapped[str] = mapped_column(String(20))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    symbol: Mapped[str] = mapped_column(String(20))
    timeframe: Mapped[Timeframe] = mapped_column(str_enum(Timeframe, "backtest_timeframe", 8))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL")
    )
    data_source: Mapped[str] = mapped_column(String(16))
    data_checksum: Mapped[str] = mapped_column(String(64), default="")
    start: Mapped[datetime]
    end: Mapped[datetime]
    initial_capital: Mapped[Decimal] = mapped_column(Money())
    account_currency: Mapped[str] = mapped_column(String(8))
    risk_settings: Mapped[dict[str, Any]] = mapped_column(JSON)
    costs: Mapped[dict[str, Any]] = mapped_column(JSON)  # spread, commission, slippage
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # split/grid settings
    progress: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    # Derived report (not queried relationally): metrics, curves, breakdowns.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_backtest_trades_backtest", "backtest_id", "entry_time"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("backtests.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[Side] = mapped_column(str_enum(Side, "bt_side", 8))
    signal_time: Mapped[datetime]
    entry_time: Mapped[datetime]
    entry_price: Mapped[Decimal] = mapped_column(Price())
    exit_time: Mapped[datetime]
    exit_price: Mapped[Decimal] = mapped_column(Price())
    exit_reason: Mapped[ExitReason] = mapped_column(str_enum(ExitReason, "bt_exit_reason", 16))
    volume: Mapped[Decimal] = mapped_column(Volume())
    stop_loss: Mapped[Decimal | None] = mapped_column(Price())  # None for Rise/Fall
    take_profit: Mapped[Decimal | None] = mapped_column(Price())
    risk_amount: Mapped[Decimal] = mapped_column(Money())
    contract_type: Mapped[str | None] = mapped_column(String(8))
    stake: Mapped[Decimal | None] = mapped_column(Money())
    payout: Mapped[Decimal | None] = mapped_column(Money())
    outcome: Mapped[str | None] = mapped_column(String(10))
    gross_pnl: Mapped[Decimal] = mapped_column(Money())
    costs: Mapped[Decimal] = mapped_column(Money())
    net_pnl: Mapped[Decimal] = mapped_column(Money())
    r_multiple: Mapped[Decimal] = mapped_column(Price())
    session: Mapped[str] = mapped_column(String(20))
    regime: Mapped[str | None] = mapped_column(String(20))  # market regime at entry
    reasons: Mapped[list[str]] = mapped_column(JSON)
