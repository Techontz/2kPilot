"""Create notifications and fan them out to channels.

In-app delivery (the `notifications` table, read by the dashboard) is always on. Additional
channels (email, Telegram, webhooks…) implement `NotificationChannel` and
are registered with `register_channel`; a failing channel never breaks the
caller or the other channels.

Every notification has a recipient: the owner of `account_id` unless
`user_id` is given; with neither it is a platform notification (admins).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.logging import mask_data
from fxrobot.db.types import utcnow
from fxrobot.domain.trading import NotificationSeverity
from fxrobot.models import Notification, TradingAccount
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
    user_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> Notification:
    default_severity, default_title = TYPES.get(type_, (NotificationSeverity.INFO, type_))
    if user_id is None and account_id is not None:
        user_id = db.scalar(select(TradingAccount.user_id).where(TradingAccount.id == account_id))
    note = Notification(
        user_id=user_id,
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
    for channel in list(_channels):
        try:
            channel.deliver(note)
        except Exception:
            logger.exception("notification channel %s failed", channel.name)
    return note
