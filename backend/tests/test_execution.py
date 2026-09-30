"""Execution engine against the PAPER broker and a real database.

Components are driven directly (not through strategy signals) so every
broker outcome — fill, rejection, lost response, timeout, disconnect — is
exercised deterministically via the paper broker's FaultInjector.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.paper import PaperBroker
from fxrobot.broker_engine.errors import (
    InvalidBrokerResponseError,
    OrderRejectedError,
)
from fxrobot.broker_engine.models import DealEntry, OrderRequest, OrderResult
from fxrobot.db.types import utcnow
from fxrobot.domain.market import Side, Timeframe
from fxrobot.domain.trading import (
    ExitReason,
    OrderPurpose,
    OrderStatus,
    OrderType,
    SignalStatus,
    TradeStatus,
)
from fxrobot.execution_engine.engine import ExecutionEngine
from fxrobot.execution_engine.reconciliation import reconcile_account
from fxrobot.models import Notification, Order, Signal, Trade, TradeEvent, TradingAccount
from fxrobot.risk_engine.engine import RiskDecision, RuleResult
from tests.test_engine_pipeline import paper_broker, setup_trading

PIP = Decimal("0.0001")  # EURUSD


# ── helpers (also used by test_reliability.py) ───────────────────────────


@dataclass
class Env:
    client: TestClient
    db: Session
    broker: PaperBroker
    trading: dict[str, Any]
    execution: ExecutionEngine

    @property
    def account_id(self) -> uuid.UUID:
        return uuid.UUID(self.trading["account"]["id"])

    @property
    def connection_id(self) -> uuid.UUID:
        return uuid.UUID(self.trading["account"]["connection_id"])

    def account(self) -> TradingAccount:
        account = self.db.get(TradingAccount, self.account_id)
        assert account is not None
        return account


def step_until_open(broker: PaperBroker, *, min_bars: int = 1) -> None:
    """Advance the simulation until the market is open (skips weekends)."""
    broker.step(min_bars)
    for _ in range(2000):
        if broker.market.is_open():
            return
        broker.step(1)
    raise AssertionError("market never opened")


def make_env(client: TestClient, db: Session) -> Env:
    trading = setup_trading(client)
    broker = paper_broker(client, trading["account"]["connection_id"])
    step_until_open(broker)
    return Env(client, db, broker, trading, ExecutionEngine())


_bar_offsets: dict[str, int] = {}


def make_signal(
    env: Env,
    *,
    side: Side = Side.BUY,
    symbol: str = "EURUSD",
    sl_pips: str = "20",
    tp_pips: str = "40",
    risk_amount: str = "20.00",
    bar_time: Any = None,
) -> Signal:
    quote = env.broker.get_quote(symbol)
    pip = env.broker.get_symbol(symbol).pip_size
    entry = quote.ask if side is Side.BUY else quote.bid
    sl = entry - Decimal(sl_pips) * pip * side.sign
    tp = entry + Decimal(tp_pips) * pip * side.sign
    if bar_time is None:
        # Unique per call so the (assignment, bar, side) constraint never trips.
        n = _bar_offsets[env.trading["account"]["id"]] = (
            _bar_offsets.get(env.trading["account"]["id"], 0) + 1
        )
        bar_time = env.broker.now() - timedelta(minutes=15 * n)
    signal = Signal(
        assignment_id=uuid.UUID(env.trading["assignment"]["id"]),
        strategy_version_id=uuid.UUID(env.trading["version"]["id"]),
        account_id=env.account_id,
        symbol=symbol,
        side=side,
        timeframe=Timeframe.M15,
        bar_time=bar_time,
        entry_type=OrderType.MARKET,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        reasons=["test signal"],
        status=SignalStatus.APPROVED,
        risk_amount=Decimal(risk_amount),
        created_at=utcnow(),
    )
    env.db.add(signal)
    env.db.commit()
    return signal


def approve(volume: str = "0.10", risk: str = "20.00") -> RiskDecision:
    return RiskDecision(
        True, [RuleResult("test", True, "ok")], Decimal(volume), Decimal(risk), None
    )


def submit(
    env: Env, signal: Signal, volume: str = "0.10", *, disconnect_first: bool = False
) -> Order:
    symbol = env.broker.get_symbol(signal.symbol)
    quote = env.broker.get_quote(signal.symbol)
    if disconnect_first:
        env.broker.faults.disconnected = True
    return env.execution.submit_entry(
        env.db,
        account=env.account(),
        signal=signal,
        decision=approve(volume, str(signal.risk_amount)),
        adapter=env.broker,
        symbol=symbol,
        quote=quote,
    )


class PlaceSpy:
    """Wraps the broker's place_order to count what actually reached it."""

    def __init__(self, broker: PaperBroker, monkeypatch: pytest.MonkeyPatch) -> None:
        self.requests: list[OrderRequest] = []
        original = broker.place_order

        def spy(request: OrderRequest) -> OrderResult:
            self.requests.append(request)
            return original(request)

        monkeypatch.setattr(broker, "place_order", spy)


def events_for(db: Session, **where: Any) -> list[str]:
    stmt = select(TradeEvent.event_type).order_by(TradeEvent.id)
    for key, value in where.items():
        stmt = stmt.where(getattr(TradeEvent, key) == value)
    return list(db.scalars(stmt))


def notification_types(db: Session) -> list[str]:
    return list(db.scalars(select(Notification.type).order_by(Notification.created_at)))


def count(db: Session, model: Any, *where: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


@pytest.fixture
def env(owner_client: TestClient, db: Session) -> Env:
    return make_env(owner_client, db)


# ── success path ─────────────────────────────────────────────────────────


def test_market_buy_fills_opens_trade_and_journals(env: Env) -> None:
    signal = make_signal(env)
    quote = env.broker.get_quote("EURUSD")
    order = submit(env, signal)

    assert order.status is OrderStatus.FILLED
    assert order.purpose is OrderPurpose.ENTRY
    assert order.attempts == 1
    assert order.is_simulated is True
    assert len(order.client_order_id) == 24 and order.client_order_id.startswith("fx")
    assert order.fill_price == quote.ask  # BUY fills at the ask, no slippage configured
    assert order.requested_price == quote.ask
    assert order.filled_volume == Decimal("0.10")
    assert order.broker_code == "PAPER_FILLED"

    env.db.refresh(signal)
    assert signal.status is SignalStatus.EXECUTED
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    assert trade.status is TradeStatus.OPEN
    assert trade.entry_price == quote.ask
    assert trade.stop_loss == signal.stop_loss == trade.initial_stop_loss
    assert trade.take_profit == signal.take_profit
    assert trade.risk_amount == Decimal("20.00")
    assert trade.slippage_pips == Decimal("0.0")
    assert trade.spread_at_entry == quote.spread
    assert trade.is_simulated is True
    assert trade.broker_position_id == order.broker_position_id

    positions = env.broker.get_positions()
    assert [(p.position_id, p.client_order_id, p.volume) for p in positions] == [
        (order.broker_position_id, order.client_order_id, Decimal("0.10"))
    ]
    assert events_for(env.db, signal_id=signal.id) == [
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "POSITION_OPENED",
    ]
    assert notification_types(env.db)[-2:] == ["order.submitted", "position.opened"]


def test_market_sell_fills_at_bid(env: Env) -> None:
    signal = make_signal(env, side=Side.SELL)
    quote = env.broker.get_quote("EURUSD")
    order = submit(env, signal)
    assert order.status is OrderStatus.FILLED
    assert order.fill_price == quote.bid
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None and trade.side is Side.SELL
    assert env.broker.get_positions()[0].side is Side.SELL


def test_adverse_slippage_is_measured_in_pips(env: Env) -> None:
    env.broker.config.slippage_points = 7  # 0.7 pip on a 5-digit symbol
    signal = make_signal(env)
    quote = env.broker.get_quote("EURUSD")
    order = submit(env, signal)
    assert order.fill_price == quote.ask + Decimal("0.00007")
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    assert trade.slippage_pips == Decimal("0.7")
    assert trade.requested_entry == signal.entry_price


def test_order_intent_is_persisted_before_the_broker_call(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[OrderStatus, int]] = []
    original = env.broker.place_order
    session_factory = env.client.app.state.session_factory  # type: ignore[attr-defined]

    def spy(request: OrderRequest) -> OrderResult:
        # A separate connection sees only committed state.
        with session_factory() as other:
            row = other.scalar(
                select(Order).where(Order.client_order_id == request.client_order_id)
            )
            assert row is not None, "order must be committed before it is sent"
            seen.append((row.status, row.attempts))
        return original(request)

    monkeypatch.setattr(env.broker, "place_order", spy)
    order = submit(env, make_signal(env))
    assert seen == [(OrderStatus.SUBMITTED, 1)]
    assert order.status is OrderStatus.FILLED


def test_unapproved_decision_is_never_executed(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = PlaceSpy(env.broker, monkeypatch)
    signal = make_signal(env)
    with pytest.raises(ValueError, match="approved"):
        env.execution.submit_entry(
            env.db,
            account=env.account(),
            signal=signal,
            decision=RiskDecision(False, [RuleResult("x", False, "no")]),
            adapter=env.broker,
            symbol=env.broker.get_symbol("EURUSD"),
            quote=env.broker.get_quote("EURUSD"),
        )
    assert spy.requests == []
    assert count(env.db, Order) == 0


# ── broker rejections ────────────────────────────────────────────────────


def test_broker_rejection_marks_order_rejected_and_signal_failed(env: Env) -> None:
    signal = make_signal(env)
    # Stop loss above the ask for a BUY: the broker refuses.
    signal.stop_loss = env.broker.get_quote("EURUSD").ask + 10 * PIP
    env.db.commit()
    order = submit(env, signal)

    assert order.status is OrderStatus.REJECTED
    assert order.broker_code == "rejected"
    assert order.broker_message == "Invalid stops: stop loss on the wrong side of price"
    assert order.trade_id is None
    env.db.refresh(signal)
    assert signal.status is SignalStatus.FAILED
    assert signal.rejection_reason == (
        "Broker rejected: Invalid stops: stop loss on the wrong side of price"
    )
    assert events_for(env.db, order_id=order.id) == ["ORDER_SUBMITTED", "ORDER_REJECTED"]
    assert notification_types(env.db)[-1] == "order.rejected"
    assert count(env.db, Trade) == 0
    assert env.broker.get_positions() == []


def test_insufficient_margin_rejection_keeps_specific_code(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal, volume="50")  # ~5.4M notional on a 10k account
    assert order.status is OrderStatus.REJECTED
    assert order.broker_code == "insufficient_margin"
    env.db.refresh(signal)
    assert signal.status is SignalStatus.FAILED
    assert env.broker.get_positions() == []
    assert env.broker.get_account().balance == Decimal("10000.00")


def test_market_closed_rejection(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    signal = make_signal(env)
    monkeypatch.setattr(env.broker.market, "is_open", lambda: False)
    order = submit(env, signal)
    assert order.status is OrderStatus.REJECTED
    assert order.broker_code == "market_closed"
    assert order.broker_message == "Market is closed"


def test_invalid_volume_step_is_rejected(env: Env) -> None:
    order = submit(env, make_signal(env), volume="0.015")
    assert order.status is OrderStatus.REJECTED
    assert "not a multiple" in (order.broker_message or "")


# ── uncertain outcomes ───────────────────────────────────────────────────


def test_lost_response_is_reconciled_to_filled_without_resending(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = PlaceSpy(env.broker, monkeypatch)
    env.broker.faults.lose_next_response = True
    signal = make_signal(env)
    order = submit(env, signal)

    # The broker executed it exactly once; we learnt that by looking it up.
    assert len(spy.requests) == 1
    assert spy.requests[0].client_order_id == order.client_order_id
    assert order.status is OrderStatus.FILLED
    assert order.last_reconciled_at is not None
    assert env.broker.faults.lose_next_response is False
    events = events_for(env.db, order_id=order.id)
    assert events == [
        "ORDER_SUBMITTED",
        "ORDER_UNKNOWN",
        "ORDER_RECONCILED",
        "ORDER_FILLED",
        "POSITION_OPENED",
    ]
    unknown = env.db.scalar(
        select(TradeEvent).where(
            TradeEvent.order_id == order.id, TradeEvent.event_type == "ORDER_UNKNOWN"
        )
    )
    assert unknown is not None and "will NOT be re-sent" in unknown.message
    assert "order.unknown" in notification_types(env.db)
    env.db.refresh(signal)
    assert signal.status is SignalStatus.EXECUTED
    assert len(env.broker.get_positions()) == 1
    assert count(env.db, Trade) == 1

    # Later reconciliation passes must not create a second trade or order.
    for _ in range(3):
        report = reconcile_account(env.db, env.account(), env.broker, env.execution)
        assert report.trades_recovered == 0 and report.external_positions == 0
    assert len(spy.requests) == 1
    assert count(env.db, Trade) == 1
    assert count(env.db, Order) == 1


def test_timeout_before_execution_stays_unknown_then_fails_after_grace(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = PlaceSpy(env.broker, monkeypatch)
    env.broker.faults.timeout_before_next_order = True
    signal = make_signal(env)
    order = submit(env, signal)

    # The broker has no record yet, but the grace period has not passed.
    assert order.status is OrderStatus.UNKNOWN
    assert order.broker_message == "Simulated timeout before execution"
    env.db.refresh(signal)
    assert signal.status is SignalStatus.APPROVED
    assert env.execution.reconcile_order(env.db, order, env.broker) is False
    assert order.status is OrderStatus.UNKNOWN

    resolved = env.execution.reconcile_order(env.db, order, env.broker, grace=timedelta(0))
    assert resolved is True
    assert order.status is OrderStatus.FAILED
    assert order.broker_message == "Broker has no record of this order — it was not executed."
    env.db.refresh(signal)
    assert signal.status is SignalStatus.FAILED
    assert len(spy.requests) == 1, "an uncertain order is never re-sent"
    assert env.broker.get_positions() == []
    assert events_for(env.db, order_id=order.id) == [
        "ORDER_SUBMITTED",
        "ORDER_UNKNOWN",
        "ORDER_FAILED",
    ]


def test_unexpected_broker_error_is_treated_as_uncertain(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def garbled(request: OrderRequest) -> OrderResult:
        calls.append(request.client_order_id)
        raise InvalidBrokerResponseError("garbled reply")

    monkeypatch.setattr(env.broker, "place_order", garbled)
    order = submit(env, make_signal(env))
    assert order.status is OrderStatus.UNKNOWN
    assert order.broker_message == "InvalidBrokerResponseError: garbled reply"
    assert len(calls) == 1


def test_disconnected_broker_fails_the_order_as_not_sent(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal, disconnect_first=True)
    assert order.status is OrderStatus.FAILED
    assert order.broker_message == "Not sent: Paper broker is disconnected (simulated fault)"
    env.db.refresh(signal)
    assert signal.status is SignalStatus.FAILED
    assert signal.rejection_reason == order.broker_message
    assert events_for(env.db, order_id=order.id) == ["ORDER_SUBMITTED", "ORDER_FAILED"]
    assert notification_types(env.db)[-1] == "order.rejected"
    env.broker.faults.disconnected = False
    assert env.broker.get_positions() == []


def test_reconcile_lookup_failure_leaves_order_unresolved(env: Env) -> None:
    env.broker.faults.timeout_before_next_order = True
    order = submit(env, make_signal(env))
    assert order.status is OrderStatus.UNKNOWN
    env.broker.faults.disconnected = True
    # Even with no grace, a failed lookup proves nothing: stay UNKNOWN.
    assert env.execution.reconcile_order(env.db, order, env.broker, grace=timedelta(0)) is False
    assert order.status is OrderStatus.UNKNOWN


def test_broker_is_idempotent_by_client_order_id(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal)
    request = OrderRequest(
        client_order_id=order.client_order_id,
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume=Decimal("0.10"),
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )
    again = env.broker.place_order(request)
    assert again.broker_position_id == order.broker_position_id
    assert len(env.broker.get_positions()) == 1


def test_apply_result_is_idempotent_for_the_same_position(env: Env) -> None:
    order = submit(env, make_signal(env))
    found = env.broker.find_order_by_client_id(order.client_order_id)
    assert found is not None
    env.execution.apply_result(env.db, order, found, adapter=env.broker)
    assert count(env.db, Trade) == 1


def test_pending_result_is_journaled(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal)
    pending = OrderResult(order.client_order_id, OrderStatus.PENDING, broker_order_id="X1")
    env.execution.apply_result(env.db, order, pending, adapter=env.broker)
    assert order.status is OrderStatus.PENDING
    assert events_for(env.db, order_id=order.id)[-1] == "ORDER_PENDING"


def test_cancelled_result_fails_an_unexecuted_signal(env: Env) -> None:
    env.broker.faults.timeout_before_next_order = True
    signal = make_signal(env)
    order = submit(env, signal)
    cancelled = OrderResult(order.client_order_id, OrderStatus.CANCELLED, broker_message="expired")
    env.execution.apply_result(env.db, order, cancelled, adapter=env.broker)
    assert order.status is OrderStatus.CANCELLED
    env.db.refresh(signal)
    assert signal.status is SignalStatus.FAILED
    assert signal.rejection_reason == "expired"


# ── exits & modifications ────────────────────────────────────────────────


def test_manual_close_books_pnl_from_broker_deals(env: Env) -> None:
    order = submit(env, make_signal(env))
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    env.broker.step(3)
    exit_order = env.execution.close_trade(env.db, trade, env.broker, reason=ExitReason.MANUAL)

    assert exit_order.purpose is OrderPurpose.EXIT
    assert exit_order.side is Side.SELL
    assert exit_order.status is OrderStatus.FILLED
    assert exit_order.trade_id == trade.id
    env.db.refresh(trade)
    assert trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is ExitReason.MANUAL
    out = [
        d
        for d in env.broker.get_deals(
            trade.entry_time - timedelta(days=1), env.broker.now() + timedelta(hours=1)
        )
        if d.position_id == trade.broker_position_id and d.entry is DealEntry.OUT
    ]
    assert len(out) == 1
    assert trade.exit_price == out[0].price == exit_order.fill_price
    assert trade.gross_pnl == out[0].profit
    assert trade.commission == Decimal("-0.70")  # 3.5/lot/side x 0.10 x 2
    assert trade.net_pnl == out[0].profit - Decimal("0.70")
    assert trade.r_multiple == (trade.net_pnl / Decimal("20.00")).quantize(Decimal("0.01"))
    # The broker's balance agrees with the journal to the cent.
    assert env.broker.get_account().balance == Decimal("10000.00") + trade.net_pnl
    assert env.broker.get_positions() == []
    assert events_for(env.db, trade_id=trade.id)[-1] == "POSITION_CLOSED"
    assert notification_types(env.db)[-1] == "position.closed"


def test_close_requires_an_open_trade(env: Env) -> None:
    order = submit(env, make_signal(env))
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    env.execution.close_trade(env.db, trade, env.broker, reason=ExitReason.MANUAL)
    with pytest.raises(ValueError, match="not open"):
        env.execution.close_trade(env.db, trade, env.broker, reason=ExitReason.MANUAL)
    assert count(env.db, Order, Order.purpose == OrderPurpose.EXIT) == 1


def test_close_with_broker_disconnected_fails_and_keeps_trade_open(env: Env) -> None:
    order = submit(env, make_signal(env))
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    env.broker.faults.disconnected = True
    exit_order = env.execution.close_trade(env.db, trade, env.broker, reason=ExitReason.MANUAL)
    assert exit_order.status is OrderStatus.FAILED
    assert trade.status is TradeStatus.OPEN
    env.broker.faults.disconnected = False
    assert len(env.broker.get_positions()) == 1


def test_modify_trade_moves_stop_at_broker_and_journals(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal)
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    new_sl = signal.stop_loss + 5 * PIP
    env.execution.modify_trade(
        env.db, trade, env.broker, stop_loss=new_sl, take_profit=signal.take_profit, actor="owner"
    )
    assert trade.stop_loss == new_sl
    assert trade.initial_stop_loss == signal.stop_loss  # the original risk is kept
    assert env.broker.get_positions()[0].stop_loss == new_sl
    assert events_for(env.db, trade_id=trade.id)[-1] == "POSITION_MODIFIED"


def test_modify_trade_refuses_to_remove_the_stop(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal)
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    with pytest.raises(ValueError, match="mandatory"):
        env.execution.modify_trade(
            env.db, trade, env.broker, stop_loss=None, take_profit=None, actor="owner"
        )
    assert env.broker.get_positions()[0].stop_loss == signal.stop_loss


def test_modify_trade_rejected_by_broker_changes_nothing(env: Env) -> None:
    signal = make_signal(env)
    order = submit(env, signal)
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    bad_sl = env.broker.get_quote("EURUSD").bid + 5 * PIP  # above price for a long
    with pytest.raises(OrderRejectedError):
        env.execution.modify_trade(
            env.db, trade, env.broker, stop_loss=bad_sl, take_profit=None, actor="owner"
        )
    env.db.rollback()
    env.db.refresh(trade)
    assert trade.stop_loss == signal.stop_loss
    assert env.broker.get_positions()[0].stop_loss == signal.stop_loss


def test_finalize_without_deal_history_records_unknown_pnl(env: Env) -> None:
    order = submit(env, make_signal(env))
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    env.execution.finalize_trade(
        env.db, trade, env.broker, deals=[], fallback_reason=ExitReason.BROKER
    )
    assert trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is ExitReason.BROKER
    assert trade.exit_price == trade.entry_price
    assert trade.net_pnl is None and trade.gross_pnl is None and trade.r_multiple is None
    messages = list(
        env.db.scalars(
            select(TradeEvent.message).where(
                TradeEvent.trade_id == trade.id, TradeEvent.event_type == "POSITION_CLOSED"
            )
        )
    )
    assert messages[0] == "Closing deal not found in broker history — P/L unknown"
    # Finalising twice is a no-op.
    env.execution.finalize_trade(env.db, trade, env.broker, deals=[])
    assert (
        count(
            env.db,
            TradeEvent,
            TradeEvent.trade_id == trade.id,
            TradeEvent.event_type == "POSITION_CLOSED",
        )
        == 2
    )
