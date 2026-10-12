from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import NOW_DEFAULT, str_enum, utcnow
from fxrobot.domain.contracts import ContractFamily, ContractSpec
from fxrobot.domain.trading import AssignmentStatus


class Strategy(TimestampMixin, Base):
    """A strategy. `user_id` NULL = built-in template registered by the engine (shared)."""

    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_strategies_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(60))  # implementation id, e.g. "trend_pullback"
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str | None] = mapped_column(String(80))  # stable id of a built-in template
    # template | builder | ai | import | copy
    source: Mapped[str] = mapped_column(String(16), default="builder")
    summary: Mapped[str] = mapped_column(String(300), default="")
    # how_it_works, struggles, suggested_timeframe/symbols/contract, difficulty
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    copied_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    # Administrator's emergency stop: no NEW entries from this strategy (or its
    # copies) for anyone. Open positions are never closed by it.
    entries_disabled_at: Mapped[datetime | None]
    entries_disabled_reason: Mapped[str | None] = mapped_column(String(300))
    entries_disabled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    copied_from: Mapped[Strategy | None] = relationship(remote_side="Strategy.id")
    versions: Mapped[list[StrategyVersion]] = relationship(
        back_populates="strategy", order_by="StrategyVersion.version"
    )


class StrategyVersion(Base):
    """Immutable parameter set. Signals, trades and backtests reference exact versions."""

    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_ver"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    version: Mapped[int]
    code_version: Mapped[str] = mapped_column(String(20))  # implementation semver
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    rules_text: Mapped[str | None] = mapped_column(Text)  # plain-English summary (rules)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    strategy: Mapped[Strategy] = relationship(back_populates="versions")


class StrategyAssignment(TimestampMixin, Base):
    """Runs one strategy version on one symbol of one account. Paused by default."""

    __tablename__ = "strategy_assignments"
    __table_args__ = (
        UniqueConstraint("account_id", "strategy_id", "symbol", name="uq_assignments_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    strategy_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    symbol: Mapped[str] = mapped_column(String(40))  # broker symbol name
    status: Mapped[AssignmentStatus] = mapped_column(
        str_enum(AssignmentStatus, "assignment_status", 16),
        default=AssignmentStatus.PAUSED,
        server_default=text("'PAUSED'"),
    )
    status_reason: Mapped[str | None] = mapped_column(String(300))
    last_bar_evaluated: Mapped[datetime | None]
    last_signal_at: Mapped[datetime | None]
    # Contract specification (see fxrobot.domain.contracts); SPOT = lots.
    contract_family: Mapped[ContractFamily] = mapped_column(
        str_enum(ContractFamily, "assignment_contract_family", 16),
        default=ContractFamily.SPOT,
        server_default=text("'SPOT'"),
    )
    duration: Mapped[int | None]
    duration_unit: Mapped[str | None] = mapped_column(String(1))
    allow_equals: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    stake: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    multiplier: Mapped[int | None]
    take_profit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stop_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    def contract_spec(self) -> ContractSpec:
        """The stored settings, validated (raises ValueError if they are inconsistent)."""
        return ContractSpec.parse(
            {
                "contract_family": self.contract_family.value,
                "duration": self.duration,
                "duration_unit": self.duration_unit,
                "allow_equals": bool(self.allow_equals) or None,
                "stake": self.stake,
                "multiplier": self.multiplier,
                "take_profit_amount": self.take_profit_amount,
                "stop_loss_amount": self.stop_loss_amount,
            }
        )


class StrategyEvaluation(Base):
    """Why a closed bar did or did not produce a signal — makes decisions explainable."""

    __tablename__ = "strategy_evaluations"
    __table_args__ = (Index("ix_strategy_evaluations_assignment_bar", "assignment_id", "bar_time"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strategy_assignments.id", ondelete="CASCADE")
    )
    bar_time: Mapped[datetime]
    outcome: Mapped[str] = mapped_column(String(20))  # SIGNAL | NO_SETUP | INSUFFICIENT_DATA
    summary: Mapped[str] = mapped_column(String(300))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
