"""Liveness / readiness probes (unauthenticated, no sensitive data)."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from fxrobot.api.deps import DbDep
from fxrobot.schemas.system import HealthOut

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _expected_heads() -> set[str]:
    return set(ScriptDirectory(str(MIGRATIONS_DIR)).get_heads())


@router.get("/live", response_model=HealthOut)
def live() -> HealthOut:
    """The process is up. Does not touch dependencies."""
    return HealthOut(status="ok")


@router.get("/ready", response_model=HealthOut)
def ready(db: DbDep, response: Response) -> HealthOut:
    """Ready to serve: database reachable and schema at the latest migration."""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
        current = set(db.scalars(text("SELECT version_num FROM alembic_version")))
        checks["migrations"] = "ok" if current == _expected_heads() else "pending"
    except SQLAlchemyError:
        logger.warning("readiness check failed", exc_info=True)
        checks.setdefault("database", "unavailable")
        checks.setdefault("migrations", "unknown")
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status="ok" if healthy else "degraded", checks=checks)
