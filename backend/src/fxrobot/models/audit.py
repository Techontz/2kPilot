from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditLog(Base):
    """Append-only record of security- and trading-relevant actions."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_occurred_at", "occurred_at"),
        Index("ix_audit_logs_action_occurred_at", "action", "occurred_at"),
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # SET NULL keeps history when a user is deleted; actor_label preserves who it was.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_label: Mapped[str] = mapped_column(String(320))  # email or "system"
    action: Mapped[str] = mapped_column(String(100))  # e.g. "trading.kill_switch.engaged"
    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, name="audit_outcome", values_callable=lambda e: [m.value for m in e])
    )
    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    # Masked before insert; small contextual payload, not a data dump.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
