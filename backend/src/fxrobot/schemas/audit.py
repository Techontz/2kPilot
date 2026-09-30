from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from fxrobot.models import AuditOutcome


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor_label: str
    action: str
    outcome: AuditOutcome
    target_type: str | None
    target_id: str | None
    ip_address: str | None
    correlation_id: str | None
    details: dict[str, Any]
