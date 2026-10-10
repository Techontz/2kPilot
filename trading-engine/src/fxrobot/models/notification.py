from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base
from fxrobot.db.types import NOW_DEFAULT, str_enum, utcnow
from fxrobot.domain.trading import NotificationSeverity


class Notification(Base):
    """In-app notification. `user_id` = recipient; NULL = platform notification (admins)."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))  # e.g. "broker.disconnected"
    severity: Mapped[NotificationSeverity] = mapped_column(
        str_enum(NotificationSeverity, "notification_severity", 16)
    )
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(1000))
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    read_at: Mapped[datetime | None]
