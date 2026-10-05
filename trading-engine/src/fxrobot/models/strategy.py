from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import NOW_DEFAULT, str_enum, utcnow
from fxrobot.domain.trading import AssignmentStatus


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(60))  # implementation id, e.g. "trend_pullback"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")

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
