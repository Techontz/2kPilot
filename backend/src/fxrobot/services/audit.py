"""Audit trail. Records are added to the caller's DB transaction."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.context import get_correlation_id
from fxrobot.core.logging import mask_data
from fxrobot.models import AuditLog, AuditOutcome, User
from fxrobot.services.context import RequestMeta

logger = logging.getLogger("fxrobot.audit")


def record(
    db: Session,
    *,
    action: str,
    outcome: AuditOutcome,
    actor: User | None,
    meta: RequestMeta,
    actor_label: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    safe_details = mask_data(details or {})
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_label=actor_label or (actor.email if actor else "system"),
        action=action,
        outcome=outcome,
        target_type=target_type,
        target_id=target_id,
        ip_address=meta.ip_address,
        user_agent=(meta.user_agent or "")[:512] or None,
        correlation_id=get_correlation_id(),
        details=safe_details,
    )
    db.add(entry)
    logger.info(
        "audit %s %s",
        action,
        outcome.value,
        extra={"audit_action": action, "audit_outcome": outcome.value, "actor": entry.actor_label},
    )
    return entry


def list_entries(db: Session, *, limit: int, before_id: int | None = None) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    return list(db.scalars(stmt))
