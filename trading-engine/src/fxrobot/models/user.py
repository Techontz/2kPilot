"""Read-only view of Laravel's `users` table, and each user's trading controls.

Users, passwords, MFA and sessions are managed by the Laravel backend. The
engine needs user ids (every account, profile, dataset… belongs to a user)
and reads each owner's `user_trading_states` row on every tick.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, text, true
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import str_enum
from fxrobot.domain.modes import TradingMode


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))  # user | admin


class UserTradingState(TimestampMixin, Base):
    """One user's own trading controls (written by Laravel, read every tick).

    A missing row is treated like the default: STOPPED, DEMO mode.
    """

    __tablename__ = "user_trading_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    trading_mode: Mapped[TradingMode] = mapped_column(
        str_enum(TradingMode, "user_trading_mode", 16),
        default=TradingMode.DEMO,
        server_default=text("'DEMO'"),
    )
    kill_switch_engaged: Mapped[bool] = mapped_column(default=True, server_default=true())
    kill_switch_reason: Mapped[str | None] = mapped_column(Text)
    kill_switch_changed_at: Mapped[datetime | None]
    mode_changed_at: Mapped[datetime | None]
    live_authorized_at: Mapped[datetime | None]
    live_authorized_limits: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # The authorisation covers exactly this account with this risk profile, as
    # the profile stood at live_authorized_at (see trading_engine.context).
    live_authorized_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL")
    )
    live_authorized_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_profiles.id", ondelete="SET NULL")
    )
