"""Manual trading actions: close / modify a position, and the emergency stop.

Stopping new trading (kill switch) and closing positions are separate
actions. The emergency stop does both, deliberately and audited.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.errors import AppError, ConflictError, NotFoundError
from fxrobot.domain.trading import ExitReason, OrderStatus, TradeStatus
from fxrobot.execution_engine.engine import ExecutionEngine
from fxrobot.models import AuditOutcome, Trade, TradingAccount, User
from fxrobot.notifications.service import notify
from fxrobot.services import audit, trading_control
from fxrobot.services.context import RequestMeta


class BrokerActionError(AppError):
    code = "broker_action_failed"


def _adapter(manager: BrokerManager, db: Session, trade: Trade):  # type: ignore[no-untyped-def]
    account = db.get(TradingAccount, trade.account_id)
    if account is None:
        raise NotFoundError("Account not found")
    try:
        return manager.get(account.connection_id)
    except BrokerError as exc:
        raise BrokerActionError(f"Broker unavailable: {exc}") from exc


def close_position(
    db: Session,
    trade_id: uuid.UUID,
    *,
    manager: BrokerManager,
    actor: User,
    meta: RequestMeta,
    reason: ExitReason = ExitReason.MANUAL,
) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise NotFoundError("Trade not found")
    if trade.status is not TradeStatus.OPEN:
        raise ConflictError("Trade is already closed")
    adapter = _adapter(manager, db, trade)
    order = ExecutionEngine().close_trade(
        db, trade, adapter, reason=reason, note=f"by {actor.email}"
    )
    audit.record(
        db,
        action="position.closed_manually",
        outcome=AuditOutcome.SUCCESS
        if order.status is OrderStatus.FILLED
        else AuditOutcome.FAILURE,
        actor=actor,
        meta=meta,
        target_type="trade",
        target_id=str(trade.id),
        details={"order_status": order.status.value, "symbol": trade.symbol},
    )
    db.commit()
    if order.status is OrderStatus.REJECTED or order.status is OrderStatus.FAILED:
        raise BrokerActionError(order.broker_message or "Close was rejected")
    return trade


def modify_position(
    db: Session,
    trade_id: uuid.UUID,
    *,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
    manager: BrokerManager,
    actor: User,
    meta: RequestMeta,
) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise NotFoundError("Trade not found")
    if trade.status is not TradeStatus.OPEN:
        raise ConflictError("Trade is closed")
    adapter = _adapter(manager, db, trade)
    try:
        ExecutionEngine().modify_trade(
            db, trade, adapter, stop_loss=stop_loss, take_profit=take_profit, actor=actor.email
        )
    except ValueError as exc:
        raise BrokerActionError(str(exc)) from exc
    except BrokerError as exc:
        raise BrokerActionError(f"Broker refused the change: {exc}") from exc
    audit.record(
        db,
        action="position.modified_manually",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="trade",
        target_id=str(trade.id),
        details={"stop_loss": str(stop_loss), "take_profit": str(take_profit)},
    )
    db.commit()
    return trade


def emergency_stop(
    db: Session,
    *,
    manager: BrokerManager,
    actor: User,
    meta: RequestMeta,
    close_positions: bool,
    reason: str,
) -> dict[str, object]:
    """Engage the kill switch; optionally close every open position."""
    trading_control.engage_kill_switch(db, actor=actor, reason=f"EMERGENCY: {reason}", meta=meta)
    closed, failed = 0, []
    if close_positions:
        for trade in list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))):
            try:
                close_position(
                    db,
                    trade.id,
                    manager=manager,
                    actor=actor,
                    meta=meta,
                    reason=ExitReason.EMERGENCY,
                )
                closed += 1
            except (AppError, BrokerError) as exc:
                failed.append(f"{trade.symbol}: {exc}")
    audit.record(
        db,
        action="trading.emergency_stop",
        outcome=AuditOutcome.SUCCESS if not failed else AuditOutcome.FAILURE,
        actor=actor,
        meta=meta,
        target_type="system",
        details={"close_positions": close_positions, "closed": closed, "failed": failed},
    )
    db.commit()
    notify(
        db,
        "trading.emergency_stop",
        f"Emergency stop by {actor.email}. Trading stopped"
        + (f"; closed {closed} position(s)" if close_positions else "; positions left open")
        + (f"; {len(failed)} could not be closed" if failed else "")
        + ".",
    )
    return {"closed": closed, "failed": failed}
