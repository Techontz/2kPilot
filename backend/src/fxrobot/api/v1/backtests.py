from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import BacktestsDep, CurrentUserDep, DbDep, MetaDep, OwnerDep
from fxrobot.backtesting.service import BacktestRequest, list_backtests, version_params
from fxrobot.core.errors import ConflictError, NotFoundError
from fxrobot.domain.trading import BacktestStatus
from fxrobot.models import AuditOutcome, Backtest, BacktestTrade
from fxrobot.services import audit

router = APIRouter(prefix="/backtests", tags=["backtests"])


class BacktestBody(BaseModel):
    mode: Literal["single", "split", "walk_forward", "sensitivity"] = "single"
    strategy_version_id: uuid.UUID | None = None
    strategy_key: str = "trend_pullback"
    parameters: dict[str, Any] | None = None
    dataset_id: uuid.UUID
    start: datetime
    end: datetime
    initial_capital: Decimal = Field(default=Decimal(10000), gt=0, le=Decimal(100_000_000))
    risk: dict[str, Any] = Field(default_factory=dict)
    costs: dict[str, Any] = Field(default_factory=dict)
    name: str = Field(default="", max_length=200)
    split_ratio: float = 0.7
    train_months: int = Field(default=6, ge=1, le=36)
    test_months: int = Field(default=2, ge=1, le=12)
    grid: dict[str, list[Any]] = Field(default_factory=dict)


@router.get("")
def list_all(
    _: CurrentUserDep, db: DbDep, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict[str, Any]]:
    return [ser.backtest(b) for b in list_backtests(db, limit)]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create(
    body: BacktestBody, owner: OwnerDep, db: DbDep, meta: MetaDep, service: BacktestsDep
) -> dict[str, Any]:
    key, params = body.strategy_key, body.parameters or {}
    if body.strategy_version_id is not None:
        key, version_parameters = version_params(db, body.strategy_version_id)
        params = {**version_parameters, **(body.parameters or {})}
    request = BacktestRequest(
        mode=body.mode,
        strategy_key=key,
        parameters=params,
        dataset_id=body.dataset_id,
        start=body.start,
        end=body.end,
        initial_capital=body.initial_capital,
        risk=body.risk,
        costs=body.costs,
        strategy_version_id=body.strategy_version_id,
        name=body.name,
        split_ratio=body.split_ratio,
        train_months=body.train_months,
        test_months=body.test_months,
        grid=body.grid,
    )
    row = service.create(db, request, owner)
    audit.record(
        db,
        action="backtest.started",
        outcome=AuditOutcome.SUCCESS,
        actor=owner,
        meta=meta,
        target_type="backtest",
        target_id=str(row.id),
        details={"mode": body.mode},
    )
    db.commit()
    return ser.backtest(row, full=True)


@router.get("/{backtest_id}")
def detail(backtest_id: uuid.UUID, _: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    row = db.get(Backtest, backtest_id)
    if row is None:
        raise NotFoundError("Backtest not found")
    children = db.scalars(
        select(Backtest).where(Backtest.parent_id == row.id).order_by(Backtest.created_at)
    )
    return ser.backtest(row, full=True) | {
        "children": [ser.backtest(c, full=True) for c in children]
    }


@router.get("/{backtest_id}/trades")
def trades(
    backtest_id: uuid.UUID,
    _: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=2000, ge=1, le=10000),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BacktestTrade)
        .where(BacktestTrade.backtest_id == backtest_id)
        .order_by(BacktestTrade.entry_time)
        .limit(limit)
    )
    return [ser.backtest_trade(t) for t in rows]


@router.delete("/{backtest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(backtest_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep) -> None:
    row = db.get(Backtest, backtest_id)
    if row is None:
        raise NotFoundError("Backtest not found")
    if row.status in (BacktestStatus.QUEUED, BacktestStatus.RUNNING):
        raise ConflictError("Wait for the backtest to finish before deleting it")
    audit.record(
        db,
        action="backtest.deleted",
        outcome=AuditOutcome.SUCCESS,
        actor=owner,
        meta=meta,
        target_type="backtest",
        target_id=str(backtest_id),
        details={"name": row.name},
    )
    db.delete(row)
    db.commit()
