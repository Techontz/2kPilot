"""The trading journal: an append-only timeline of every lifecycle step."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from fxrobot.core.context import get_correlation_id
from fxrobot.core.events import bus
from fxrobot.core.logging import mask_data
from fxrobot.db.types import utcnow
from fxrobot.models import TradeEvent


class EventType:
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    SIGNAL_SKIPPED = "SIGNAL_SKIPPED"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_PENDING = "ORDER_PENDING"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FAILED = "ORDER_FAILED"
    ORDER_UNKNOWN = "ORDER_UNKNOWN"
    ORDER_RECONCILED = "ORDER_RECONCILED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_MODIFIED = "POSITION_MODIFIED"
    POSITION_CLOSED = "POSITION_CLOSED"
    EXTERNAL_POSITION = "EXTERNAL_POSITION"
    ACCOUNT_HALTED = "ACCOUNT_HALTED"


def record(
    db: Session,
    event_type: str,
    message: str,
    *,
    account_id: uuid.UUID | None,
    signal_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    trade_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> TradeEvent:
    event = TradeEvent(
        occurred_at=utcnow(),
        account_id=account_id,
        signal_id=signal_id,
        order_id=order_id,
        trade_id=trade_id,
        event_type=event_type,
        message=message[:500],
        data=mask_data(data or {}),
        correlation_id=get_correlation_id(),
    )
    db.add(event)
    db.flush()
    bus.publish(
        "journal",
        {
            "id": event.id,
            "event_type": event_type,
            "message": event.message,
            "account_id": str(account_id) if account_id else None,
            "trade_id": str(trade_id) if trade_id else None,
        },
    )
    return event
