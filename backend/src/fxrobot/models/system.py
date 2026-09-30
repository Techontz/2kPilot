from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, SmallInteger, Text, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base
from fxrobot.domain.modes import TradingMode


class SystemState(Base):
    """Singleton row (id=1) holding global trading controls.

    The kill switch defaults to ENGAGED: a fresh install cannot trade
    until someone deliberately resumes trading.
    """

    __tablename__ = "system_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    trading_mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", values_callable=lambda e: [m.value for m in e]),
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
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
