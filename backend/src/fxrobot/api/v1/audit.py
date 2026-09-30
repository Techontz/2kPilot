from __future__ import annotations

from fastapi import APIRouter, Query

from fxrobot.api.deps import DbDep, OwnerDep
from fxrobot.schemas.audit import AuditLogOut
from fxrobot.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    _: OwnerDep,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
) -> list[AuditLogOut]:
    """Newest first. Page with `before_id` = the last id you received."""
    return [
        AuditLogOut.model_validate(e)
        for e in audit.list_entries(db, limit=limit, before_id=before_id)
    ]
