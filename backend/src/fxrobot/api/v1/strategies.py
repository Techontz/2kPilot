from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, MetaDep, OwnerDep
from fxrobot.core.errors import NotFoundError
from fxrobot.domain.trading import AssignmentStatus, BacktestStatus, TradeStatus
from fxrobot.models import (
    Backtest,
    Signal,
    Strategy,
    StrategyAssignment,
    StrategyEvaluation,
    StrategyVersion,
    Trade,
    TradingAccount,
)
from fxrobot.services import strategies as svc
from fxrobot.strategy_engine import get_strategy

router = APIRouter(prefix="/strategies", tags=["strategies"])


class VersionBody(BaseModel):
    parameters: dict[str, Any]
    notes: str = Field(default="", max_length=500)


class AssignmentBody(BaseModel):
    strategy_version_id: uuid.UUID
    account_id: uuid.UUID
    symbol: str = Field(min_length=3, max_length=40)


class AssignmentVersionBody(BaseModel):
    strategy_version_id: uuid.UUID


class PauseBody(BaseModel):
    reason: str = Field(default="", max_length=300)


def _version(v: StrategyVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version": v.version,
        "code_version": v.code_version,
        "parameters": v.parameters,
        "notes": v.notes,
        "created_at": ser.t(v.created_at),
    }


def _assignment(db: DbDep, a: StrategyAssignment) -> dict[str, Any]:
    account = db.get(TradingAccount, a.account_id)
    version = db.get(StrategyVersion, a.strategy_version_id)
    last_eval = db.scalar(
        select(StrategyEvaluation)
        .where(StrategyEvaluation.assignment_id == a.id)
        .order_by(StrategyEvaluation.id.desc())
        .limit(1)
    )
    last_signal = db.scalar(
        select(Signal)
        .where(Signal.assignment_id == a.id)
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    return {
        "id": str(a.id),
        "strategy_id": str(a.strategy_id),
        "symbol": a.symbol,
        "status": a.status.value,
        "status_reason": a.status_reason,
        "account": {
            "id": str(account.id),
            "label": account.label,
            "environment": account.environment.value,
            "trading_enabled": account.trading_enabled,
        }
        if account
        else None,
        "version": version.version if version else None,
        "strategy_version_id": str(a.strategy_version_id),
        "last_bar_evaluated": ser.t(a.last_bar_evaluated),
        "last_evaluation": {
            "outcome": last_eval.outcome,
            "summary": last_eval.summary,
            "bar_time": ser.t(last_eval.bar_time),
            "checks": last_eval.checks,
        }
        if last_eval
        else None,
        "last_signal": ser.signal(last_signal) if last_signal else None,
    }


def _strategy(db: DbDep, s: Strategy) -> dict[str, Any]:
    impl = get_strategy(s.key)
    version_ids = [v.id for v in s.versions]
    trades = (
        db.execute(
            select(func.count(), func.coalesce(func.sum(Trade.net_pnl), 0)).where(
                Trade.strategy_version_id.in_(version_ids), Trade.status == TradeStatus.CLOSED
            )
        ).one()
        if version_ids
        else (0, 0)
    )
    last_trade = (
        db.scalar(
            select(Trade)
            .where(Trade.strategy_version_id.in_(version_ids))
            .order_by(Trade.entry_time.desc())
            .limit(1)
        )
        if version_ids
        else None
    )
    last_bt = db.scalar(
        select(Backtest)
        .where(Backtest.strategy_key == s.key, Backtest.parent_id.is_(None))
        .order_by(Backtest.created_at.desc())
        .limit(1)
    )
    assignments = list(
        db.scalars(select(StrategyAssignment).where(StrategyAssignment.strategy_id == s.id))
    )
    return {
        "id": str(s.id),
        "key": s.key,
        "name": s.name,
        "description": s.description,
        "code_version": impl.code_version,
        "timeframes": [
            tf.value for tf in impl.timeframes(impl.parse_params(s.versions[-1].parameters))
        ]
        if s.versions
        else [],
        "versions": [_version(v) for v in s.versions],
        "parameter_schema": impl.Params.model_json_schema(),
        "assignments": [_assignment(db, a) for a in assignments],
        "status": "ENABLED"
        if any(a.status is AssignmentStatus.ENABLED for a in assignments)
        else "PAUSED",
        "performance": {"closed_trades": int(trades[0]), "net_pnl": str(trades[1])},
        "last_trade": ser.trade(last_trade) if last_trade else None,
        "last_backtest": ser.backtest(last_bt) if last_bt else None,
        "backtest_status": last_bt.status.value if last_bt else None,
        "backtest_completed": bool(last_bt and last_bt.status is BacktestStatus.COMPLETED),
    }


@router.get("")
def list_strategies(_: CurrentUserDep, db: DbDep) -> list[dict[str, Any]]:
    return [_strategy(db, s) for s in db.scalars(select(Strategy).order_by(Strategy.name))]


@router.get("/{strategy_id}")
def get_strategy_detail(strategy_id: uuid.UUID, _: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    s = db.get(Strategy, strategy_id)
    if s is None:
        raise NotFoundError("Strategy not found")
    return _strategy(db, s)


@router.post("/{strategy_id}/versions", status_code=status.HTTP_201_CREATED)
def create_version(
    strategy_id: uuid.UUID, body: VersionBody, owner: OwnerDep, db: DbDep, meta: MetaDep
) -> dict[str, Any]:
    return _version(
        svc.create_version(db, strategy_id, body.parameters, body.notes, actor=owner, meta=meta)
    )


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: AssignmentBody, owner: OwnerDep, db: DbDep, meta: MetaDep
) -> dict[str, Any]:
    a = svc.create_assignment(
        db,
        strategy_version_id=body.strategy_version_id,
        account_id=body.account_id,
        symbol=body.symbol,
        actor=owner,
        meta=meta,
    )
    return _assignment(db, a)


@router.post("/assignments/{assignment_id}/enable")
def enable(assignment_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep) -> dict[str, Any]:
    return _assignment(
        db,
        svc.set_assignment_status(
            db, assignment_id, AssignmentStatus.ENABLED, actor=owner, meta=meta
        ),
    )


@router.post("/assignments/{assignment_id}/pause")
def pause(
    assignment_id: uuid.UUID, body: PauseBody, owner: OwnerDep, db: DbDep, meta: MetaDep
) -> dict[str, Any]:
    return _assignment(
        db,
        svc.set_assignment_status(
            db, assignment_id, AssignmentStatus.PAUSED, actor=owner, meta=meta, reason=body.reason
        ),
    )


@router.put("/assignments/{assignment_id}/version")
def change_version(
    assignment_id: uuid.UUID, body: AssignmentVersionBody, owner: OwnerDep, db: DbDep, meta: MetaDep
) -> dict[str, Any]:
    return _assignment(
        db,
        svc.update_assignment_version(
            db, assignment_id, body.strategy_version_id, actor=owner, meta=meta
        ),
    )


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(assignment_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep) -> None:
    svc.delete_assignment(db, assignment_id, actor=owner, meta=meta)


@router.get("/assignments/{assignment_id}/evaluations")
def evaluations(
    assignment_id: uuid.UUID,
    _: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=50, ge=1, le=500),
    outcome: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(StrategyEvaluation).where(StrategyEvaluation.assignment_id == assignment_id)
    if outcome:
        stmt = stmt.where(StrategyEvaluation.outcome == outcome)
    rows = db.scalars(stmt.order_by(StrategyEvaluation.id.desc()).limit(limit))
    return [
        {
            "id": e.id,
            "bar_time": ser.t(e.bar_time),
            "outcome": e.outcome,
            "summary": e.summary,
            "checks": e.checks,
            "created_at": ser.t(e.created_at),
        }
        for e in rows
    ]
