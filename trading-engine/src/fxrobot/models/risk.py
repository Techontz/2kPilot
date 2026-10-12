from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base, TimestampMixin


class RiskProfile(TimestampMixin, Base):
    """Typed risk limits (deliberately columns, not JSON). Assigned per account.

    A NULL limit means "not applied"; the mandatory stop loss and the global
    gates cannot be turned off.
    """

    __tablename__ = "risk_profiles"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_risk_profiles_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    max_position_lots: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_open_positions: Mapped[int | None]
    max_positions_per_symbol: Mapped[int | None]
    max_symbol_exposure_lots: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_total_exposure_lots: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    max_total_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    max_daily_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    max_weekly_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    max_trades_per_day: Mapped[int | None]
    max_spread_pips: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    max_slippage_pips: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    min_stop_pips: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    max_stop_pips: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    min_reward_risk: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # e.g. ["LONDON", "NEW_YORK"]; empty list = any session.
    allowed_sessions: Mapped[list[str]] = mapped_column(JSON, default=list)
    trading_hours_start: Mapped[str | None] = mapped_column(String(5))  # "HH:MM" UTC
    trading_hours_end: Mapped[str | None] = mapped_column(String(5))
    cooldown_after_losses: Mapped[int | None]
    cooldown_minutes: Mapped[int | None]
    max_data_age_seconds: Mapped[int] = mapped_column(default=120)
    # Stake-based limits for contracts (account currency).
    stake_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("1.00"))
    max_stake_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_daily_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    max_consecutive_losses: Mapped[int | None]
    daily_profit_target_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # No new trades while the balance is below this (NULL = off).
    min_account_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
