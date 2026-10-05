from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, SmallInteger, String, Text, text, true
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base
from fxrobot.db.types import NOW_DEFAULT, str_enum, utcnow
from fxrobot.domain.modes import TradingMode


class SystemState(Base):
    """Singleton row (id=1) holding global trading controls and engine liveness.

    The kill switch defaults to ENGAGED: a fresh install cannot trade
    until someone deliberately resumes trading.
    """

    __tablename__ = "system_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False, default=1)
    trading_mode: Mapped[TradingMode] = mapped_column(
        str_enum(TradingMode, "trading_mode", 16),
        default=TradingMode.DEMO,
        server_default=text("'DEMO'"),
    )
    kill_switch_engaged: Mapped[bool] = mapped_column(default=True, server_default=true())
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    kill_switch_changed_at: Mapped[datetime | None]
    kill_switch_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    mode_changed_at: Mapped[datetime | None]
    mode_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Trading-engine leadership lease: only one process may run the engine.
    engine_owner: Mapped[str | None] = mapped_column(String(100))
    engine_lease_until: Mapped[datetime | None]
    engine_heartbeat_at: Mapped[datetime | None]
    engine_detail: Mapped[str | None] = mapped_column(String(500))
    engine_degraded: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=NOW_DEFAULT
    )


class SystemSetting(Base):
    """Operator-level settings that are not secrets (secrets live in env / encrypted columns)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=NOW_DEFAULT
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
