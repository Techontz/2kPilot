"""Positions, orders, trade history, signals and the journal."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep
from fxrobot.core.errors import NotFoundError
from fxrobot.domain.trading import OrderStatus, SignalStatus, TradeStatus
from fxrobot.models import (
    Order,
    Signal,
    Strategy,
    StrategyEvaluation,
    StrategyVersion,
    Trade,
    TradeEvent,
    TradingAccount,
)
from fxrobot.services import trading_ops

router = APIRouter(tags=["trading records"])


class ModifyBody(BaseModel):
    stop_loss: Decimal
    take_profit: Decimal | None = None


def _labels(db: DbDep) -> dict[uuid.UUID, TradingAccount]:
    return {a.id: a for a in db.scalars(select(TradingAccount))}


def _strategy_names(db: DbDep) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(StrategyVersion.id, Strategy.name, StrategyVersion.version).join(
            Strategy, StrategyVersion.strategy_id == Strategy.id
        )
    ).all()
    return {vid: f"{name} v{ver}" for vid, name, ver in rows}


def _trade_row(
    x: Trade, accounts: dict[uuid.UUID, TradingAccount], names: dict[uuid.UUID, str]
) -> dict[str, Any]:
    account = accounts.get(x.account_id)
    return ser.trade(
        x,
        account_label=account.label if account else None,
        account_environment=account.environment.value if account else None,
        strategy=names.get(x.strategy_version_id) if x.strategy_version_id else None,
    )


@router.get("/positions")
def positions(
    _: CurrentUserDep, db: DbDep, account_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    stmt = select(Trade).where(Trade.status == TradeStatus.OPEN)
    if account_id:
        stmt = stmt.where(Trade.account_id == account_id)
    accounts, names = _labels(db), _strategy_names(db)
    return [
        _trade_row(x, accounts, names) for x in db.scalars(stmt.order_by(Trade.entry_time.desc()))
    ]


@router.post("/positions/{trade_id}/close")
def close_position(
    trade_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep, manager: ManagerDep
) -> dict[str, Any]:
    trade = trading_ops.close_position(db, trade_id, manager=manager, actor=owner, meta=meta)
    return ser.trade(trade)


@router.put("/positions/{trade_id}")
def modify_position(
    trade_id: uuid.UUID,
    body: ModifyBody,
    owner: OwnerDep,
    db: DbDep,
    meta: MetaDep,
    manager: ManagerDep,
) -> dict[str, Any]:
    trade = trading_ops.modify_position(
        db,
        trade_id,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        manager=manager,
        actor=owner,
        meta=meta,
    )
    return ser.trade(trade)


@router.get("/orders")
def orders(
    _: CurrentUserDep,
    db: DbDep,
    account_id: uuid.UUID | None = None,
    status: OrderStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Order)
    if account_id:
        stmt = stmt.where(Order.account_id == account_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if before:
        stmt = stmt.where(Order.created_at < before)
    return [ser.order(o) for o in db.scalars(stmt.order_by(Order.created_at.desc()).limit(limit))]


@router.get("/trades")
def trades(
    _: CurrentUserDep,
    db: DbDep,
    account_id: uuid.UUID | None = None,
    symbol: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Trade).where(Trade.status == TradeStatus.CLOSED)
    if account_id:
        stmt = stmt.where(Trade.account_id == account_id)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if before:
        stmt = stmt.where(Trade.exit_time < before)
    accounts, names = _labels(db), _strategy_names(db)
    return [
        _trade_row(x, accounts, names)
        for x in db.scalars(stmt.order_by(Trade.exit_time.desc()).limit(limit))
    ]


@router.get("/trades/{trade_id}")
def trade_lifecycle(trade_id: uuid.UUID, _: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    """Signal → risk decision → execution → position → exit, in one view."""
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise NotFoundError("Trade not found")
    signal = db.get(Signal, trade.signal_id) if trade.signal_id else None
    evaluation = None
    if signal and signal.assignment_id:
        ev = db.scalar(
            select(StrategyEvaluation)
            .where(
                StrategyEvaluation.assignment_id == signal.assignment_id,
                StrategyEvaluation.bar_time == signal.bar_time,
            )
            .limit(1)
        )
        if ev:
            evaluation = {"outcome": ev.outcome, "summary": ev.summary, "checks": ev.checks}
    trade_orders = db.scalars(
        select(Order)
        .where(
            (Order.trade_id == trade.id)
            | ((Order.signal_id == trade.signal_id) & (Order.signal_id.is_not(None)))
        )
        .order_by(Order.created_at)
    )
    events = db.scalars(
        select(TradeEvent)
        .where(
            (TradeEvent.trade_id == trade.id)
            | ((TradeEvent.signal_id == trade.signal_id) & (TradeEvent.signal_id.is_not(None)))
        )
        .order_by(TradeEvent.id)
    )
    return {
        "trade": _trade_row(trade, _labels(db), _strategy_names(db)),
        "signal": ser.signal(signal) if signal else None,
        "evaluation": evaluation,
        "orders": [ser.order(o) for o in trade_orders],
        "events": [ser.event(e) for e in events],
    }


@router.get("/signals")
def signals(
    _: CurrentUserDep,
    db: DbDep,
    account_id: uuid.UUID | None = None,
    status: SignalStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    stmt = select(Signal)
    if account_id:
        stmt = stmt.where(Signal.account_id == account_id)
    if status:
        stmt = stmt.where(Signal.status == status)
    return [ser.signal(s) for s in db.scalars(stmt.order_by(Signal.created_at.desc()).limit(limit))]


@router.get("/journal")
def journal(
    _: CurrentUserDep,
    db: DbDep,
    account_id: uuid.UUID | None = None,
    event_type: str | None = None,
    trade_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1),
) -> list[dict[str, Any]]:
    stmt = select(TradeEvent)
    if account_id:
        stmt = stmt.where(TradeEvent.account_id == account_id)
    if event_type:
        stmt = stmt.where(TradeEvent.event_type == event_type)
    if trade_id:
        stmt = stmt.where(TradeEvent.trade_id == trade_id)
    if before_id:
        stmt = stmt.where(TradeEvent.id < before_id)
    return [ser.event(e) for e in db.scalars(stmt.order_by(TradeEvent.id.desc()).limit(limit))]
