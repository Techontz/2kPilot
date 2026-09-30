"""Create notifications and fan them out to channels.

In-app delivery (database + live event stream) is always on. Additional
channels (email, Telegram, webhooks…) implement `NotificationChannel` and
are registered with `register_channel`; a failing channel never breaks the
caller or the other channels.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from fxrobot.core.events import bus
from fxrobot.core.logging import mask_data
from fxrobot.db.types import utcnow
from fxrobot.domain.trading import NotificationSeverity
from fxrobot.models import Notification
from fxrobot.notifications.types import TYPES

logger = logging.getLogger(__name__)


class NotificationChannel(Protocol):
    name: str

    def deliver(self, notification: Notification) -> None: ...


_channels: list[NotificationChannel] = []


def register_channel(channel: NotificationChannel) -> None:
    _channels.append(channel)


def clear_channels() -> None:
    _channels.clear()


def notify(
    db: Session,
    type_: str,
    message: str,
    *,
    title: str | None = None,
    severity: NotificationSeverity | None = None,
    account_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> Notification:
    default_severity, default_title = TYPES.get(type_, (NotificationSeverity.INFO, type_))
    note = Notification(
        type=type_,
        severity=severity or default_severity,
        title=(title or default_title)[:200],
        message=message[:1000],
        account_id=account_id,
        data=mask_data(data or {}),
        created_at=utcnow(),
    )
    db.add(note)
    if commit:
        db.commit()
    else:
        db.flush()
    bus.publish("notification", serialize(note))
    for channel in list(_channels):
        try:
            channel.deliver(note)
        except Exception:
            logger.exception("notification channel %s failed", channel.name)
    return note


def serialize(note: Notification) -> dict[str, Any]:
    return {
        "id": note.id,
        "type": note.type,
        "severity": note.severity.value,
        "title": note.title,
        "message": note.message,
        "account_id": str(note.account_id) if note.account_id else None,
        "data": note.data,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "read_at": note.read_at.isoformat() if note.read_at else None,
    }


def list_notifications(
    db: Session, *, limit: int, before_id: int | None, unread_only: bool, severity: str | None
) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.id.desc()).limit(limit)
    if before_id:
        stmt = stmt.where(Notification.id < before_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if severity:
        stmt = stmt.where(Notification.severity == NotificationSeverity(severity))
    return list(db.scalars(stmt))


def unread_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).where(Notification.read_at.is_(None))) or 0)


def mark_read(db: Session, ids: list[int] | None, at: datetime | None = None) -> int:
    stmt = update(Notification).where(Notification.read_at.is_(None)).values(read_at=at or utcnow())
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    result = db.execute(stmt)
    db.commit()
    bus.publish("notification_read", {"ids": ids})
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
