"""Strategies, immutable versions, and account assignments."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from fxrobot.db.types import utcnow
from fxrobot.domain.trading import AssignmentStatus
from fxrobot.models import (
    AuditOutcome,
    Strategy,
    StrategyAssignment,
    StrategyVersion,
    TradingAccount,
    User,
)
from fxrobot.notifications.service import notify
from fxrobot.services import audit
from fxrobot.services.context import RequestMeta
from fxrobot.strategy_engine import get_strategy, list_strategies


class StrategyConfigError(AppError):
    code = "invalid_strategy_config"


def ensure_builtin_strategies(db: Session) -> None:
    """Create a catalogue row (with version 1 = defaults) for each built-in strategy."""
    for impl in list_strategies():
        if db.scalar(select(Strategy.id).where(Strategy.key == impl.key)) is not None:
            continue
        strategy = Strategy(key=impl.key, name=impl.name, description=impl.description)
        db.add(strategy)
        db.flush()
        db.add(
            StrategyVersion(
                strategy_id=strategy.id,
                version=1,
                code_version=impl.code_version,
                parameters=impl.default_params(),
                notes="Default research parameters",
                created_at=utcnow(),
            )
        )
    db.commit()


def validate_params(key: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_strategy(key).parse_params(params).model_dump(mode="json")
    except KeyError as exc:
        raise StrategyConfigError(str(exc)) from exc
    except ValueError as exc:
        raise StrategyConfigError(f"Invalid parameters: {exc}") from exc


def create_version(
    db: Session,
    strategy_id: uuid.UUID,
    params: dict[str, Any],
    notes: str,
    *,
    actor: User,
    meta: RequestMeta,
) -> StrategyVersion:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise NotFoundError("Strategy not found")
    clean = validate_params(strategy.key, params)
    latest = (
        db.scalar(
            select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy.id
            )
        )
        or 0
    )
    version = StrategyVersion(
        strategy_id=strategy.id,
        version=latest + 1,
        code_version=get_strategy(strategy.key).code_version,
        parameters=clean,
        notes=notes[:500],
        created_by=actor.id,
        created_at=utcnow(),
    )
    db.add(version)
    db.flush()
    audit.record(
        db,
        action="strategy.version_created",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="strategy",
        target_id=str(strategy.id),
        details={"version": version.version},
    )
    db.commit()
    return version


def create_assignment(
    db: Session,
    *,
    strategy_version_id: uuid.UUID,
    account_id: uuid.UUID,
    symbol: str,
    actor: User,
    meta: RequestMeta,
) -> StrategyAssignment:
    version = db.get(StrategyVersion, strategy_version_id)
    account = db.get(TradingAccount, account_id)
    if version is None or account is None:
        raise NotFoundError("Strategy version or account not found")
    symbol = symbol.strip()
    if not symbol:
        raise StrategyConfigError("Symbol is required")
    existing = db.scalar(
        select(StrategyAssignment).where(
            StrategyAssignment.account_id == account_id,
            StrategyAssignment.strategy_id == version.strategy_id,
            StrategyAssignment.symbol == symbol,
        )
    )
    if existing is not None:
        raise ConflictError("This strategy already runs on that symbol for this account")
    assignment = StrategyAssignment(
        strategy_id=version.strategy_id,
        strategy_version_id=version.id,
        account_id=account_id,
        symbol=symbol,
        status=AssignmentStatus.PAUSED,
        status_reason="Created paused — enable deliberately",
    )
    db.add(assignment)
    db.flush()
    audit.record(
        db,
        action="strategy.assigned",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="strategy_assignment",
        target_id=str(assignment.id),
        details={"account": account.label, "symbol": symbol, "version": version.version},
    )
    db.commit()
    return assignment


def set_assignment_status(
    db: Session,
    assignment_id: uuid.UUID,
    status: AssignmentStatus,
    *,
    actor: User,
    meta: RequestMeta,
    reason: str = "",
) -> StrategyAssignment:
    assignment = db.get(StrategyAssignment, assignment_id)
    if assignment is None:
        raise NotFoundError("Assignment not found")
    if status is AssignmentStatus.ENABLED:
        account = db.get(TradingAccount, assignment.account_id)
        if account is None or account.risk_profile_id is None:
            raise PermissionDeniedError("Assign a risk profile to the account first")
    assignment.status = status
    assignment.status_reason = reason[:300] or (
        f"{'Enabled' if status is AssignmentStatus.ENABLED else 'Paused'} by {actor.email}"
    )
    audit.record(
        db,
        action=f"strategy.{'enabled' if status is AssignmentStatus.ENABLED else 'paused'}",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="strategy_assignment",
        target_id=str(assignment.id),
        details={"symbol": assignment.symbol},
    )
    db.commit()
    if status is AssignmentStatus.PAUSED:
        notify(
            db,
            "strategy.paused",
            f"{assignment.symbol}: {assignment.status_reason}",
            account_id=assignment.account_id,
        )
    return assignment


def update_assignment_version(
    db: Session,
    assignment_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    actor: User,
    meta: RequestMeta,
) -> StrategyAssignment:
    assignment = db.get(StrategyAssignment, assignment_id)
    version = db.get(StrategyVersion, version_id)
    if assignment is None or version is None:
        raise NotFoundError("Assignment or version not found")
    if version.strategy_id != assignment.strategy_id:
        raise StrategyConfigError("Version belongs to a different strategy")
    assignment.strategy_version_id = version.id
    assignment.status = (
        AssignmentStatus.PAUSED
    )  # a new configuration must be re-enabled deliberately
    assignment.status_reason = f"Switched to v{version.version} — re-enable to trade"
    audit.record(
        db,
        action="strategy.modified",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="strategy_assignment",
        target_id=str(assignment.id),
        details={"version": version.version},
    )
    db.commit()
    return assignment


def delete_assignment(
    db: Session, assignment_id: uuid.UUID, *, actor: User, meta: RequestMeta
) -> None:
    assignment = db.get(StrategyAssignment, assignment_id)
    if assignment is None:
        raise NotFoundError("Assignment not found")
    audit.record(
        db,
        action="strategy.unassigned",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="strategy_assignment",
        target_id=str(assignment.id),
        details={"symbol": assignment.symbol},
    )
    db.delete(assignment)
    db.commit()
