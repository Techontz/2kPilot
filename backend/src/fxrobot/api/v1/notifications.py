from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from fxrobot.api.deps import CurrentUserDep, DbDep
from fxrobot.domain.trading import NotificationSeverity
from fxrobot.notifications import service as svc
from fxrobot.notifications.types import TYPES

router = APIRouter(prefix="/notifications", tags=["notifications"])


class MarkReadBody(BaseModel):
    ids: list[int] | None = None  # None = all


@router.get("")
def list_notifications(
    _: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    unread_only: bool = False,
    severity: NotificationSeverity | None = None,
) -> dict[str, Any]:
    items = svc.list_notifications(
        db, limit=limit, before_id=before_id, unread_only=unread_only, severity=severity
    )
    return {
        "items": [svc.serialize(n) for n in items],
        "unread": svc.unread_count(db),
        "types": {k: {"severity": v[0].value, "title": v[1]} for k, v in TYPES.items()},
    }


@router.get("/unread-count")
def unread(_: CurrentUserDep, db: DbDep) -> dict[str, int]:
    return {"unread": svc.unread_count(db)}


@router.post("/read")
def mark_read(body: MarkReadBody, _: CurrentUserDep, db: DbDep) -> dict[str, int]:
    return {"updated": svc.mark_read(db, body.ids)}
