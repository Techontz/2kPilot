"""Actions a person takes from the dashboard (always via Laravel, which
authenticates, authorises and audits them):

* manual tickets — preview (risk check only) and submit;
* close / modify a position;
* close every open position (the separate "Close positions" emergency action).

A manual ticket goes through EXACTLY the same risk engine and execution engine
as an automated signal. There is no shortcut: kill switch, live lock, account
enabled, stop-loss requirement, loss limits, exposure… all apply.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.context import new_correlation_id, set_correlation_id
from fxrobot.core.errors import AppError, BrokerUnavailableError, ConflictError, NotFoundError
from fxrobot.db.types import utcnow
from fxrobot.domain.market import Quote, Side, SymbolInfo, Timeframe
from fxrobot.domain.trading import (
    ExitReason,
    OrderStatus,
    OrderType,
    SignalSource,
    SignalStatus,
    TradeStatus,
)
from fxrobot.execution_engine import journal
from fxrobot.execution_engine.engine import ExecutionEngine
from fxrobot.execution_engine.journal import EventType
from fxrobot.execution_engine.reconciliation import unresolved_orders
from fxrobot.market_data.conversion import point_value
from fxrobot.models import Order, RiskProfile, Signal, SystemState, Trade, TradingAccount
from fxrobot.notifications.service import notify
from fxrobot.risk_engine.engine import (
    RiskDecision,
    evaluate,
    size_position,
)
from fxrobot.services.risk_profiles import limits_of
from fxrobot.strategy_engine.base import SignalIntent
from fxrobot.trading_engine.context import build_risk_context


class BrokerActionError(AppError):
    code = "broker_action_failed"


@dataclass(frozen=True)
class ManualTicket:
    account_id: uuid.UUID
    symbol: str
    side: Side
    stop_loss: Decimal
    take_profit: Decimal | None
    volume: Decimal | None = None  # None (preview only) = suggest the maximum allowed
    order_type: OrderType = OrderType.MARKET
    idempotency_key: str | None = None
    actor_id: uuid.UUID | None = None
    actor_label: str = "dashboard"


@dataclass
class Preview:
    approved: bool
    checks: list[dict[str, Any]]
    entry_price: Decimal | None
    spread: Decimal | None
    volume: Decimal | None
    suggested_volume: Decimal | None
    risk_amount: Decimal | None
    reward_risk: Decimal | None
    reward_amount: Decimal | None
    currency: str
    symbol: SymbolInfo | None
    rejection_reason: str | None
    notes: list[str] = field(default_factory=list)


def _account(db: Session, account_id: uuid.UUID) -> TradingAccount:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    return account


def _adapter(manager: BrokerManager, account: TradingAccount) -> BrokerAdapter:
    try:
        return manager.get(account.connection_id)
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Broker unavailable: {exc}") from exc


def _intent(ticket: ManualTicket, quote: Quote, now_bar: Any) -> SignalIntent:
    entry = quote.ask if ticket.side is Side.BUY else quote.bid
    return SignalIntent(
        side=ticket.side,
        timeframe=Timeframe.M1,
        bar_time=now_bar,
        entry_price=entry,
        stop_loss=ticket.stop_loss,
        take_profit=ticket.take_profit,
        reasons=[f"Manual ticket by {ticket.actor_label}"],
        entry_type=ticket.order_type,
    )


def _decide(
    db: Session,
    account: TradingAccount,
    adapter: BrokerAdapter,
    ticket: ManualTicket,
    live_locked: bool,
    volume: Decimal | None,
) -> tuple[SignalIntent, RiskDecision, SymbolInfo, Quote, Decimal | None]:
    symbol = adapter.get_symbol(ticket.symbol)
    quote = adapter.get_quote(symbol.name)
    state = db.get(SystemState, 1)
    if state is None:
        raise ConflictError("System state is missing; run the database migrations")
    ctx = build_risk_context(
        db,
        account=account,
        adapter=adapter,
        state=state,
        live_locked=live_locked,
        symbol=symbol,
        account_info=None,
        broker_connected=adapter.is_connected,
    )
    ctx.manual = True
    intent = _intent(ticket, quote, Timeframe.M1.floor(ctx.now))
    profile = db.get(RiskProfile, account.risk_profile_id) if account.risk_profile_id else None
    if profile is None:
        decision = RiskDecision(
            False, [_rule("Risk profile", False, "no risk profile assigned to this account")]
        )
        return intent, decision, symbol, quote, None
    limits = limits_of(profile)
    decision = evaluate(intent, ctx, limits, requested_volume=volume)
    # Sizing shown on the ticket even when another rule fails (display only).
    try:
        suggestion = size_position(intent, ctx, limits).volume
    except (ArithmeticError, TypeError, ValueError):
        suggestion = None
    if ticket.order_type is not OrderType.MARKET:
        decision.approved = False
        decision.checks.insert(
            0, _rule("Order type", False, "only market orders are supported for manual tickets")
        )
    return intent, decision, symbol, quote, suggestion


def _rule(name: str, passed: bool, detail: str) -> Any:
    from fxrobot.risk_engine.engine import RuleResult

    return RuleResult(name, passed, detail)


def preview_ticket(
    db: Session, manager: BrokerManager, ticket: ManualTicket, *, live_locked: bool
) -> Preview:
    """Run the full risk check without sending anything."""
    account = _account(db, ticket.account_id)
    adapter = _adapter(manager, account)
    try:
        intent, decision, symbol, quote, suggested = _decide(
            db, account, adapter, ticket, live_locked, ticket.volume
        )
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Broker did not answer: {exc}") from exc
    finally:
        db.rollback()  # preview never writes
    volume = decision.volume or ticket.volume or suggested
    risk_amount = decision.risk_amount
    if risk_amount is None and volume is not None:
        risk_amount = _estimated_risk(db, manager, ticket, volume, live_locked)
    reward = None
    if risk_amount is not None and intent.reward_risk is not None:
        reward = (risk_amount * intent.reward_risk).quantize(Decimal("0.01"))
    notes = (
        list(adapter.capabilities.notes)
        if not adapter.is_simulated
        else ["PAPER account: simulated execution, no real money."]
    )
    return Preview(
        approved=decision.approved,
        checks=decision.checks_json(),
        entry_price=intent.entry_price,
        spread=quote.spread,
        volume=volume,
        suggested_volume=suggested,
        risk_amount=risk_amount,
        reward_risk=intent.reward_risk.quantize(Decimal("0.01")) if intent.reward_risk else None,
        reward_amount=reward,
        currency=account.currency,
        symbol=symbol,
        rejection_reason=decision.rejection_reason,
        notes=notes,
    )


def _estimated_risk(
    db: Session,
    manager: BrokerManager,
    ticket: ManualTicket,
    volume: Decimal,
    live_locked: bool,
) -> Decimal | None:
    """Money at risk if the stop is hit, for display when a rule blocked the ticket."""
    account = _account(db, ticket.account_id)
    adapter = _adapter(manager, account)
    try:
        symbol = adapter.get_symbol(ticket.symbol)
        quote = adapter.get_quote(symbol.name)
        state = db.get(SystemState, 1)
        if state is None:
            return None
        ctx = build_risk_context(
            db,
            account=account,
            adapter=adapter,
            state=state,
            live_locked=live_locked,
            symbol=symbol,
            account_info=None,
            broker_connected=adapter.is_connected,
        )
        intent = _intent(ticket, quote, Timeframe.M1.floor(ctx.now))
        value = point_value(symbol, account.currency, ctx.quote_lookup)
        if value is None:
            return None
        return (volume * intent.risk_distance / symbol.point * value).quantize(Decimal("0.01"))
    except (BrokerError, ArithmeticError, TypeError, ValueError):
        return None
    finally:
        db.rollback()


def submit_ticket(
    db: Session,
    manager: BrokerManager,
    ticket: ManualTicket,
    *,
    live_locked: bool,
    execution: ExecutionEngine | None = None,
) -> Signal:
    """Risk-check and execute a confirmed manual ticket. Idempotent per key."""
    if not ticket.idempotency_key or ticket.volume is None:
        raise ConflictError("A confirmed ticket needs a volume and an idempotency key")
    existing = db.scalar(select(Signal).where(Signal.idempotency_key == ticket.idempotency_key))
    if existing is not None:
        return existing  # double-click / retried request: never a second order
    account = _account(db, ticket.account_id)
    if unresolved_orders(db, account.id):
        raise ConflictError(
            "An earlier order on this account is still being reconciled with the broker. "
            "New orders are blocked until its outcome is known."
        )
    adapter = _adapter(manager, account)
    try:
        intent, decision, symbol, quote, _ = _decide(
            db, account, adapter, ticket, live_locked, ticket.volume
        )
    except BrokerError as exc:
        raise BrokerUnavailableError(f"Broker did not answer: {exc}") from exc
    cid = new_correlation_id()
    set_correlation_id(cid)
    signal = Signal(
        source=SignalSource.MANUAL,
        account_id=account.id,
        created_by=ticket.actor_id,
        idempotency_key=ticket.idempotency_key,
        symbol=symbol.name,
        side=intent.side,
        timeframe=intent.timeframe,
        bar_time=intent.bar_time,
        entry_type=intent.entry_type,
        entry_price=intent.entry_price,
        stop_loss=intent.stop_loss,
        take_profit=intent.take_profit,
        reasons=intent.reasons,
        status=SignalStatus.NEW,
        risk_checks=decision.checks_json(),
        requested_volume=ticket.volume,
        correlation_id=cid,
        created_at=utcnow(),
        decided_at=utcnow(),
    )
    db.add(signal)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()  # the same key arrived concurrently
        again = db.scalar(select(Signal).where(Signal.idempotency_key == ticket.idempotency_key))
        if again is None:
            raise
        return again
    prefix = "PAPER " if adapter.is_simulated else ""
    journal.record(
        db,
        EventType.SIGNAL_GENERATED,
        f"{prefix}Manual {intent.side.value} {ticket.volume.normalize()} {symbol.name} "
        f"ticket by {ticket.actor_label}",
        account_id=account.id,
        signal_id=signal.id,
        data={
            "source": "MANUAL",
            "entry": str(intent.entry_price),
            "stop_loss": str(intent.stop_loss),
            "take_profit": str(intent.take_profit),
            "volume": str(ticket.volume),
        },
    )
    if not decision.approved:
        reason = decision.rejection_reason or "rejected"
        signal.status = SignalStatus.REJECTED
        signal.rejection_reason = f"Trade rejected: {reason}"[:500]
        journal.record(
            db,
            EventType.RISK_REJECTED,
            signal.rejection_reason,
            account_id=account.id,
            signal_id=signal.id,
            data={"checks": decision.checks_json()},
        )
        db.commit()
        notify(
            db,
            "risk.rejected",
            f"Manual {intent.side.value} {symbol.name}: {reason}",
            account_id=account.id,
            data={"signal_id": str(signal.id)},
        )
        return signal
    signal.status = SignalStatus.APPROVED
    signal.volume, signal.risk_amount = decision.volume, decision.risk_amount
    journal.record(
        db,
        EventType.RISK_APPROVED,
        f"Risk approved {decision.volume} {adapter.capabilities.volume_unit}, "
        f"risking {decision.risk_amount} {account.currency}",
        account_id=account.id,
        signal_id=signal.id,
    )
    db.commit()
    (execution or ExecutionEngine()).submit_entry(
        db,
        account=account,
        signal=signal,
        decision=decision,
        adapter=adapter,
        symbol=symbol,
        quote=quote,
    )
    db.refresh(signal)
    return signal


def ticket_result(db: Session, signal: Signal) -> dict[str, Any]:
    order = db.scalar(select(Order).where(Order.signal_id == signal.id))
    trade = db.scalar(select(Trade).where(Trade.signal_id == signal.id))
    return {
        "signal_id": str(signal.id),
        "status": signal.status.value,
        "rejection_reason": signal.rejection_reason,
        "risk_checks": signal.risk_checks,
        "volume": str(signal.volume) if signal.volume is not None else None,
        "risk_amount": str(signal.risk_amount) if signal.risk_amount is not None else None,
        "order": None
        if order is None
        else {
            "id": str(order.id),
            "status": order.status.value,
            "fill_price": str(order.fill_price) if order.fill_price is not None else None,
            "broker_message": order.broker_message,
            "is_simulated": order.is_simulated,
        },
        "trade_id": str(trade.id) if trade else None,
    }


# ── positions ────────────────────────────────────────────────────────────


def _open_trade(db: Session, trade_id: uuid.UUID) -> Trade:
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise NotFoundError("Position not found")
    if trade.status is not TradeStatus.OPEN:
        raise ConflictError("This position is already closed")
    return trade


def close_position(
    db: Session,
    manager: BrokerManager,
    trade_id: uuid.UUID,
    *,
    actor_label: str,
    reason: ExitReason = ExitReason.MANUAL,
) -> Order:
    trade = _open_trade(db, trade_id)
    adapter = _adapter(manager, _account(db, trade.account_id))
    order = ExecutionEngine().close_trade(
        db, trade, adapter, reason=reason, note=f"by {actor_label}"
    )
    if order.status in (OrderStatus.REJECTED, OrderStatus.FAILED):
        raise BrokerActionError(order.broker_message or "The broker refused to close")
    return order


def modify_position(
    db: Session,
    manager: BrokerManager,
    trade_id: uuid.UUID,
    *,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
    actor_label: str,
) -> Trade:
    trade = _open_trade(db, trade_id)
    adapter = _adapter(manager, _account(db, trade.account_id))
    try:
        ExecutionEngine().modify_trade(
            db, trade, adapter, stop_loss=stop_loss, take_profit=take_profit, actor=actor_label
        )
    except ValueError as exc:
        raise BrokerActionError(str(exc)) from exc
    except BrokerError as exc:
        raise BrokerActionError(f"Broker refused the change: {exc}") from exc
    return trade


def close_all_positions(db: Session, manager: BrokerManager, *, actor_label: str) -> dict[str, Any]:
    """The deliberate "Close positions" action. The kill switch is handled by Laravel."""
    closed, failed = 0, []
    for trade in list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN))):
        try:
            close_position(
                db, manager, trade.id, actor_label=actor_label, reason=ExitReason.EMERGENCY
            )
            closed += 1
        except (AppError, BrokerError) as exc:
            failed.append({"symbol": trade.symbol, "trade_id": str(trade.id), "error": str(exc)})
    with contextlib.suppress(Exception):
        notify(
            db,
            "trading.emergency_stop",
            f"Close positions by {actor_label}: closed {closed}"
            + (f", {len(failed)} could not be closed" if failed else "")
            + ".",
        )
    return {"closed": closed, "failed": failed}
