from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from fxrobot.api.deps import CurrentUserDep, DbDep
from fxrobot.services import analytics as svc

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/performance")
def performance(
    _: CurrentUserDep,
    db: DbDep,
    account_id: uuid.UUID | None = None,
    days: int | None = Query(default=None, ge=1, le=3650),
) -> dict[str, Any]:
    """Statistics from stored trades and snapshots only — never sample numbers."""
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    return svc.performance(db, account_id, since)
