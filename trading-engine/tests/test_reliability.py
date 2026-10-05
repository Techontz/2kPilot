"""Reliability: reconciliation, restart recovery, external positions, data
problems, database outages and engine leadership."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from fxrobot.broker_engine.adapters.paper import PaperBroker
from fxrobot.broker_engine.errors import BrokerConnectionError
from fxrobot.broker_engine.models import Candle, DealEntry, OrderRequest, Quote
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
from fxrobot.execution_engine.ids import new_client_order_id
from fxrobot.execution_engine.reconciliation import reconcile_account
from fxrobot.models import (
    Order,
    Signal,
    StrategyAssignment,
    StrategyEvaluation,
    StrategyVersion,
    SystemState,
    Trade,
    TradeEvent,
)
from fxrobot.strategy_engine.base import SignalIntent
from fxrobot.trading_engine.engine import TradingEngine
from fxrobot.trading_engine.runner import _RunnerState
from tests.conftest import SignedClient
from tests.test_engine_pipeline import LOOSE_RISK, engine_for, paper_broker, run_until
from tests.test_execution import (
    PIP,
    Env,
    PlaceSpy,
    count,
    events_for,
    make_env,
    make_signal,
    notification_types,
    submit,
)


@pytest.fixture
def env(client: SignedClient, db: Session) -> Env:
    return make_env(client, db)


def reconcile(env: Env) -> Any:
    return reconcile_account(env.db, env.account(), env.broker, env.execution)


def order_row(env: Env, cid: str, *, status: OrderStatus, age: timedelta, signal: Signal) -> Order:
    """An entry order as the DB would hold it after a crash mid-submission."""
    order = Order(
        client_order_id=cid,
        account_id=env.account_id,
        signal_id=signal.id,
        purpose=OrderPurpose.ENTRY,
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume=Decimal("0.10"),
        requested_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        status=status,
        attempts=0 if status is OrderStatus.PENDING_SUBMIT else 1,
        submitted_at=None if status is OrderStatus.PENDING_SUBMIT else utcnow() - age,
        is_simulated=True,
    )
    env.db.add(order)
    env.db.commit()
    return order


def broker_buy(broker: PaperBroker, cid: str, *, symbol: str = "EURUSD", **kw: Any) -> str:
    result = broker.place_order(
        OrderRequest(
            client_order_id=cid,
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume=Decimal(kw.get("volume", "0.10")),
            stop_loss=kw.get("stop_loss"),
            take_profit=kw.get("take_profit"),
        )
    )
    assert result.broker_position_id is not None
    return result.broker_position_id


def open_trade(env: Env) -> Trade:
    order = submit(env, make_signal(env))
    trade = env.db.get(Trade, order.trade_id)
    assert trade is not None
    return trade


def step_until_flat(broker: PaperBroker, max_bars: int = 400) -> None:
    for _ in range(max_bars):
        if not broker.get_positions():
            return
        broker.step(1)
    raise AssertionError("position never closed")


# ── restart recovery ─────────────────────────────────────────────────────


def test_restart_recovers_submitted_order_whose_position_exists(
    client: SignedClient, env: Env
) -> None:
    """Crash after sending, before recording the fill: on restart the order is
    resolved from the broker and the trade appears — nothing is re-sent."""
    signal = make_signal(env)
    cid = new_client_order_id()
    order = order_row(env, cid, status=OrderStatus.SUBMITTED, age=timedelta(0), signal=signal)
    position_id = broker_buy(env.broker, cid, stop_loss=signal.stop_loss)

    # "Restart": the adapter is rebuilt from persisted paper state.
    app: Any = client.app
    app.state.broker_manager.evict(env.connection_id)
    restarted = paper_broker(client, str(env.connection_id))
    assert restarted is not env.broker
    assert [p.position_id for p in restarted.get_positions()] == [position_id]

    results = engine_for(client).tick_once()
    assert results[0].ok, results[0].detail
    env.db.expire_all()
    assert order.status is OrderStatus.FILLED
    assert order.broker_position_id == position_id
    trades = list(env.db.scalars(select(Trade)))
    assert len(trades) == 1
    assert trades[0].broker_position_id == position_id
    assert trades[0].status is TradeStatus.OPEN
    assert trades[0].signal_id == signal.id
    assert signal.status is SignalStatus.EXECUTED
    assert len(restarted.get_positions()) == 1
    assert "ORDER_RECONCILED" in events_for(env.db, order_id=order.id)


def test_position_from_our_order_is_recovered_when_lookup_misses(env: Env) -> None:
    """The broker lost the order record, but its position carries our
    client_order_id: it is recovered as our trade, not as an external one."""
    signal = make_signal(env)
    cid = new_client_order_id()
    order = order_row(env, cid, status=OrderStatus.SUBMITTED, age=timedelta(0), signal=signal)
    position_id = broker_buy(env.broker, cid, stop_loss=signal.stop_loss)
    del env.broker._acct.results[cid]
    fill = env.broker.get_positions()[0].open_price

    report = reconcile(env)
    assert report.trades_recovered == 1
    assert report.external_positions == 0
    env.db.refresh(order)
    assert order.status is OrderStatus.FILLED
    assert order.fill_price == fill
    assert order.filled_volume == Decimal("0.10")
    trade = env.db.scalar(select(Trade))
    assert trade is not None and trade.broker_position_id == position_id
    assert trade.entry_price == fill
    assert trade.signal_id == signal.id
    assert trade.risk_amount == Decimal("20.00")  # known risk, not "unknown external"
    env.db.refresh(signal)
    assert signal.status is SignalStatus.EXECUTED
    assert "reconciliation.mismatch" not in notification_types(env.db)


def test_order_wrongly_failed_is_corrected_when_its_position_appears(env: Env) -> None:
    """Past the grace period the broker had no record, so the order was marked
    FAILED — but the position carrying our id proves it executed."""
    signal = make_signal(env)
    cid = new_client_order_id()
    order = order_row(
        env, cid, status=OrderStatus.SUBMITTED, age=timedelta(minutes=5), signal=signal
    )
    position_id = broker_buy(env.broker, cid, stop_loss=signal.stop_loss)
    del env.broker._acct.results[cid]

    report = reconcile(env)
    assert report.orders_resolved == 1  # (wrongly) resolved as FAILED first…
    assert report.trades_recovered == 1  # …then corrected by the position
    assert report.external_positions == 0
    env.db.refresh(order)
    env.db.refresh(signal)
    assert order.status is OrderStatus.FILLED
    assert order.broker_position_id == position_id
    trade = env.db.scalar(select(Trade))
    assert trade is not None and order.trade_id == trade.id
    assert signal.status is SignalStatus.EXECUTED
    assert events_for(env.db, order_id=order.id) == [
        "ORDER_FAILED",
        "ORDER_RECONCILED",
        "ORDER_FILLED",
        "POSITION_OPENED",
    ]


def test_crash_before_send_is_failed_without_sending(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = PlaceSpy(env.broker, monkeypatch)
    signal = make_signal(env)
    order = order_row(
        env,
        new_client_order_id(),
        status=OrderStatus.PENDING_SUBMIT,
        age=timedelta(0),
        signal=signal,
    )
    report = reconcile(env)
    assert report.orders_resolved == 1
    env.db.refresh(order)
    env.db.refresh(signal)
    assert order.status is OrderStatus.FAILED
    assert signal.status is SignalStatus.FAILED
    assert spy.requests == []
    assert env.broker.get_positions() == []


def test_paper_state_survives_restart_and_stays_idempotent(client: SignedClient, env: Env) -> None:
    trade = open_trade(env)
    order = env.db.scalar(select(Order))
    assert order is not None
    balance = env.broker.get_account().balance
    app: Any = client.app
    app.state.broker_manager.evict(env.connection_id)
    restarted = paper_broker(client, str(env.connection_id))
    assert restarted.get_account().balance == balance
    assert restarted.now() == env.broker.now()
    found = restarted.find_order_by_client_id(order.client_order_id)
    assert found is not None and found.broker_position_id == trade.broker_position_id
    # Re-sending the same client id after a restart must not open a second position.
    broker_buy(restarted, order.client_order_id, stop_loss=trade.stop_loss)
    assert len(restarted.get_positions()) == 1


# ── positions closed at the broker ───────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "reason", "notification"),
    [
        ("sl", ExitReason.STOP_LOSS, "position.stop_loss"),
        ("tp", ExitReason.TAKE_PROFIT, "position.take_profit"),
    ],
)
def test_broker_side_exit_is_detected_with_reason_and_pnl(
    env: Env, kind: str, reason: ExitReason, notification: str
) -> None:
    trade = open_trade(env)
    position_id = trade.broker_position_id
    assert position_id is not None
    bid = env.broker.get_quote("EURUSD").bid
    # Pull the level right next to price so the very next bars trigger it.
    if kind == "sl":
        env.broker._acct.positions[position_id].sl = bid - Decimal("0.00002")
    else:
        env.broker._acct.positions[position_id].tp = bid + Decimal("0.00002")
    step_until_flat(env.broker)

    report = reconcile(env)
    assert report.trades_closed == 1
    env.db.refresh(trade)
    deals = [
        d
        for d in env.broker.get_deals(
            trade.entry_time - timedelta(days=1), env.broker.now() + timedelta(minutes=5)
        )
        if d.position_id == position_id
    ]
    exit_deal = next(d for d in deals if d.entry is DealEntry.OUT)
    assert exit_deal.reason == kind.upper()
    assert trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is reason
    assert trade.exit_price == exit_deal.price
    assert trade.exit_time == exit_deal.time
    assert trade.gross_pnl == exit_deal.profit
    assert trade.commission == Decimal("-0.70")
    assert trade.net_pnl == exit_deal.profit - Decimal("0.70")
    assert env.broker.get_account().balance == Decimal("10000.00") + trade.net_pnl
    assert notification_types(env.db)[-1] == notification
    # Idempotent: a second pass changes nothing.
    assert reconcile(env).trades_closed == 0


def test_missing_position_without_deal_history_is_not_closed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    trade = open_trade(env)
    env.broker._acct.positions.clear()  # gone at the broker…

    def no_history(*_: Any) -> list[Any]:
        raise BrokerConnectionError("history timeout")

    monkeypatch.setattr(env.broker, "get_deals", no_history)  # …and history unavailable
    report = reconcile(env)
    assert report.trades_closed == 0
    assert report.notes == ["deal history unavailable: history timeout"]
    env.db.refresh(trade)
    assert trade.status is TradeStatus.OPEN  # never guess an exit


def test_positions_unavailable_leaves_trades_untouched(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    trade = open_trade(env)

    def down() -> list[Any]:
        raise BrokerConnectionError("link down")

    monkeypatch.setattr(env.broker, "get_positions", down)
    report = reconcile(env)
    assert report.notes == ["positions unavailable: link down"]
    env.db.refresh(trade)
    assert trade.status is TradeStatus.OPEN


def test_terminal_edits_are_synced_into_the_journal(env: Env) -> None:
    trade = open_trade(env)
    position_id = trade.broker_position_id
    assert position_id is not None
    new_sl = trade.stop_loss - 3 * PIP  # type: ignore[operator]
    env.broker.modify_position(position_id, new_sl, None)
    env.broker.close_position(position_id, new_client_order_id(), Decimal("0.04"))
    reconcile(env)
    env.db.refresh(trade)
    assert trade.stop_loss == new_sl
    assert trade.take_profit is None
    assert trade.volume == Decimal("0.06")
    assert trade.initial_stop_loss != new_sl
    modified = env.db.scalar(
        select(TradeEvent).where(
            TradeEvent.trade_id == trade.id, TradeEvent.event_type == "POSITION_MODIFIED"
        )
    )
    assert modified is not None
    assert modified.message.startswith("Changed at the broker: SL ")
    assert modified.message.endswith("→0.06")
    assert "TP " in modified.message and "→None" in modified.message


# ── external positions ───────────────────────────────────────────────────


def test_external_position_is_tracked_and_flagged(env: Env) -> None:
    position_id = broker_buy(env.broker, "manual-terminal-1", symbol="USDJPY", volume="0.01")
    report = reconcile(env)
    assert report.external_positions == 1
    trade = env.db.scalar(select(Trade))
    assert trade is not None
    assert trade.broker_position_id == position_id
    assert trade.signal_id is None and trade.risk_amount is None
    assert trade.symbol == "USDJPY" and trade.volume == Decimal("0.01")
    assert trade.status is TradeStatus.OPEN
    assert events_for(env.db, trade_id=trade.id) == ["EXTERNAL_POSITION"]
    assert notification_types(env.db)[-1] == "reconciliation.mismatch"
    # Tracked from now on: a second pass does not flag it again.
    assert reconcile(env).external_positions == 0
    assert count(env.db, Trade) == 1


def test_external_position_blocks_new_entries_until_closed(client: SignedClient, env: Env) -> None:
    position_id = broker_buy(env.broker, "manual-terminal-2", symbol="USDJPY", volume="0.01")
    connection_id = str(env.connection_id)
    run_until(
        client,
        connection_id,
        env.db,
        lambda: count(env.db, Signal, Signal.status != SignalStatus.NEW) > 0,
    )
    signals = list(env.db.scalars(select(Signal)))
    assert signals
    assert all(s.status is SignalStatus.REJECTED for s in signals)
    assert any(
        "Total exposure: risk of an open position is unknown" in (s.rejection_reason or "")
        for s in signals
    )
    assert count(env.db, Order) == 0
    assert "reconciliation.mismatch" in notification_types(env.db)

    # Closed outside 2kFX too: the tracked trade closes as MANUAL; entries resume.
    env.broker.close_position(position_id, "manual-close-2")
    engine_for(client).tick_once()
    env.db.expire_all()
    external = env.db.scalar(select(Trade).where(Trade.broker_position_id == position_id))
    assert external is not None
    assert external.status is TradeStatus.CLOSED
    assert external.exit_reason is ExitReason.MANUAL
    run_until(client, connection_id, env.db, lambda: count(env.db, Order) > 0)


# ── entry gating ─────────────────────────────────────────────────────────


def test_unresolved_order_blocks_new_entries(client: SignedClient, env: Env) -> None:
    signal = make_signal(env)
    order = order_row(
        env,
        new_client_order_id(),
        status=OrderStatus.UNKNOWN,
        age=timedelta(seconds=5),
        signal=signal,
    )
    engine = engine_for(client)
    for _ in range(6):
        env.broker.step(1)
        results = engine.tick_once()
        assert results[0].ok and results[0].detail == "waiting for order reconciliation"
    env.db.expire_all()
    assert count(env.db, StrategyEvaluation) == 0
    assert count(env.db, Signal) == 1  # only ours

    # After the grace period the broker's silence proves it never executed.
    order.submitted_at = utcnow() - timedelta(minutes=5)
    env.db.commit()
    env.broker.step(1)
    results = engine.tick_once()
    assert results[0].detail == "ok"
    env.db.expire_all()
    assert order.status is OrderStatus.FAILED
    assert count(env.db, StrategyEvaluation) >= 1


def test_duplicate_signal_is_rejected_by_unique_constraint(env: Env) -> None:
    signal = make_signal(env)
    duplicate = Signal(
        assignment_id=signal.assignment_id,
        strategy_version_id=signal.strategy_version_id,
        account_id=signal.account_id,
        symbol=signal.symbol,
        side=signal.side,
        timeframe=signal.timeframe,
        bar_time=signal.bar_time,
        entry_type=signal.entry_type,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        reasons=["again"],
        created_at=utcnow(),
    )
    env.db.add(duplicate)
    with pytest.raises(IntegrityError):
        env.db.commit()
    env.db.rollback()
    # The opposite side on the same bar is a different signal.
    make_signal(env, side=Side.SELL, bar_time=signal.bar_time)
    assert count(env.db, Signal) == 2


def _runner_args(client: SignedClient, env: Env) -> dict[str, Any]:
    assignment = env.db.get(StrategyAssignment, uuid.UUID(env.trading["assignment"]["id"]))
    version = env.db.get(StrategyVersion, uuid.UUID(env.trading["version"]["id"]))
    state = env.db.get(SystemState, 1)
    return {
        "account": env.account(),
        "assignment": assignment,
        "version": version,
        "adapter": env.broker,
        "state": state,
        "rs": _RunnerState(),
    }


def _intent(env: Env, bar_time: datetime, side: Side = Side.BUY) -> SignalIntent:
    quote = env.broker.get_quote("EURUSD")
    entry = quote.ask
    return SignalIntent(
        side=side,
        timeframe=Timeframe.M15,
        bar_time=bar_time,
        entry_price=entry,
        stop_loss=entry - 20 * PIP * side.sign,
        take_profit=entry + 40 * PIP * side.sign,
        reasons=["test intent"],
    )


def test_runner_ignores_duplicate_signal_for_same_bar(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = PlaceSpy(env.broker, monkeypatch)
    runner = engine_for(client).runner
    bar = env.broker.now() - timedelta(minutes=15)
    runner._handle_signal(env.db, intent=_intent(env, bar), **_runner_args(client, env))
    first = env.db.scalar(select(Signal))
    assert first is not None
    first_status = first.status
    orders = count(env.db, Order)
    sent = len(spy.requests)

    runner._handle_signal(env.db, intent=_intent(env, bar), **_runner_args(client, env))
    env.db.expire_all()
    assert count(env.db, Signal) == 1
    assert count(env.db, Order) == orders
    assert len(spy.requests) == sent
    assert env.db.get(Signal, first.id).status is first_status  # type: ignore[union-attr]
    assert count(env.db, TradeEvent, TradeEvent.event_type == "SIGNAL_GENERATED") == 1


# ── market data problems ─────────────────────────────────────────────────


def test_malformed_candles_skip_evaluation(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = env.broker.get_candles

    def corrupt(*args: Any, **kwargs: Any) -> list[Candle]:
        candles = original(*args, **kwargs)
        if candles:
            bad = candles[-1]
            candles = [*candles[:-1], dataclasses.replace(bad, high=bad.low - PIP)]
        return candles

    monkeypatch.setattr(env.broker, "get_candles", corrupt)
    engine = engine_for(client)
    for _ in range(8):  # two hours of M15 bars → at least two closed H1 entry bars
        env.broker.step(1)
        assert engine.tick_once()[0].ok
    env.db.expire_all()
    evaluations = list(env.db.scalars(select(StrategyEvaluation)))
    assert len(evaluations) >= 2
    assert len({e.bar_time for e in evaluations}) == len(evaluations)  # once per bar
    assert {e.outcome for e in evaluations} == {"INSUFFICIENT_DATA"}
    assert {e.summary for e in evaluations} == {
        "Malformed market data received — evaluation skipped."
    }
    assert count(env.db, Signal) == 0
    stale = [t for t in notification_types(env.db) if t == "data.stale"]
    assert len(stale) == len({e.bar_time.date() for e in evaluations})  # once per day


def test_missing_latest_bar_is_not_evaluated(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = env.broker.get_candles
    monkeypatch.setattr(env.broker, "get_candles", lambda *a, **k: original(*a, **k)[:-1])
    engine = engine_for(client)
    for _ in range(4):
        env.broker.step(1)
        engine.tick_once()
    env.db.expire_all()
    assert count(env.db, Signal) == 0
    assert all(e.outcome == "INSUFFICIENT_DATA" for e in env.db.scalars(select(StrategyEvaluation)))


def test_stale_quote_rejects_signals(client: SignedClient, db: Session) -> None:
    from tests.test_engine_pipeline import setup_trading

    trading = setup_trading(client, db, risk={**LOOSE_RISK, "max_data_age_seconds": 60})
    connection_id = trading["account"]["connection_id"]
    broker = paper_broker(client, connection_id)
    original = broker.get_quote

    def old_quote(symbol: str) -> Quote:
        q = original(symbol)
        return dataclasses.replace(q, time=q.time - timedelta(hours=1))

    broker.get_quote = old_quote  # type: ignore[method-assign]
    run_until(client, connection_id, db, lambda: count(db, Signal) > 0)
    signals = list(db.scalars(select(Signal)))
    assert all(s.status is SignalStatus.REJECTED for s in signals)
    assert signals[0].rejection_reason == (
        "Trade rejected: Market data fresh: price is 3600s old (max 60s)"
    )
    assert count(db, Order) == 0


def test_signal_from_an_old_bar_is_rejected(client: SignedClient, env: Env) -> None:
    runner = engine_for(client).runner
    old_bar = env.broker.now() - timedelta(hours=2)
    runner._handle_signal(env.db, intent=_intent(env, old_bar), **_runner_args(client, env))
    signal = env.db.scalar(select(Signal))
    assert signal is not None
    assert signal.status is SignalStatus.REJECTED
    assert signal.rejection_reason == (
        "Trade rejected: Market data fresh: signal bar closed 6300s ago (max 450s)"
    )
    assert count(env.db, Order) == 0


# ── database interruptions ───────────────────────────────────────────────


def _dead_session_factory() -> sessionmaker[Session]:
    dead = create_engine(
        "mysql+pymysql://root@127.0.0.1:1/unreachable",
        poolclass=NullPool,
        connect_args={"connect_timeout": 1},
    )
    return sessionmaker(dead)


def test_engine_loop_survives_database_outage(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = engine_for(client)
    real_sf = engine._sf
    engine._sf = _dead_session_factory()
    engine.tick_seconds = 0
    original = engine.run_cycle
    seen: list[bool] = []

    def cycle() -> Any:
        seen.append(engine._db_down_notified)
        if len(seen) == 3:
            engine._sf = real_sf  # the database comes back
        if len(seen) == 4:
            engine._stop.set()
        return original()

    monkeypatch.setattr(engine, "run_cycle", cycle)
    engine._loop()  # returns only because the stop event was set: it never crashed

    assert seen == [False, True, True, False]
    assert engine._db_down_notified is False
    assert engine.is_leader
    env.db.expire_all()
    state = env.db.get(SystemState, 1)
    assert state is not None and state.engine_heartbeat_at is not None
    assert "system.error" not in notification_types(env.db)
    engine._stop.clear()


def test_engine_loop_reports_unexpected_errors_and_continues(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = engine_for(client)
    engine.tick_seconds = 0
    calls: list[int] = []

    def cycle() -> list[Any]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 2:
            raise OperationalError("SELECT 1", {}, Exception("gone away"))
        engine._stop.set()
        return []

    monkeypatch.setattr(engine, "run_cycle", cycle)
    engine._loop()
    assert len(calls) == 3
    env.db.expire_all()
    assert notification_types(env.db).count("system.error") == 1
    engine._stop.clear()


def test_account_tick_database_error_marks_engine_degraded(
    client: SignedClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = engine_for(client)

    def broken(db: Session, account_id: uuid.UUID) -> Any:
        raise OperationalError("UPDATE", {}, Exception("lost connection"))

    monkeypatch.setattr(engine.runner, "tick", broken)
    results = engine.tick_once()
    assert len(results) == 1 and not results[0].ok
    assert results[0].detail.startswith("internal error:")
    env.db.expire_all()
    state = env.db.get(SystemState, 1)
    assert state is not None and state.engine_degraded is True
    assert count(env.db, Order) == 0


def test_lease_release_and_error_notification_tolerate_dead_database(
    client: SignedClient,
) -> None:
    engine = TradingEngine(
        _dead_session_factory(),
        engine_for(client).manager,
        live_locked=True,
    )
    try:
        engine._release_lease()  # must not raise
        engine._notify_error("x")  # must not raise
        with pytest.raises(OperationalError):
            engine.run_cycle()
    finally:
        engine._pool.shutdown(wait=False)


# ── engine leadership ────────────────────────────────────────────────────


def test_only_one_engine_leads(client: SignedClient, env: Env) -> None:
    app: Any = client.app
    first = engine_for(client)
    second = TradingEngine(app.state.session_factory, app.state.broker_manager, live_locked=True)
    try:
        assert first.tick_once(), "the first engine acquires the lease and works"
        assert first.is_leader
        assert second.tick_once() == []
        assert second.is_leader is False
        env.db.expire_all()
        state = env.db.get(SystemState, 1)
        assert state is not None and state.engine_owner == first.owner
        lease_until = state.engine_lease_until
        assert lease_until is not None and lease_until > utcnow()

        # The leader keeps renewing; the follower keeps waiting.
        assert first.tick_once()
        assert second.tick_once() == []

        # The leader dies without releasing: after the lease expires, the other takes over.
        env.db.execute(
            text(
                "UPDATE system_state SET engine_lease_until = "
                "UTC_TIMESTAMP(6) - INTERVAL 1 SECOND WHERE id = 1"
            )
        )
        env.db.commit()
        assert second.tick_once()
        assert second.is_leader
        assert first.tick_once() == []
        assert first.is_leader is False
        env.db.expire_all()
        assert env.db.get(SystemState, 1).engine_owner == second.owner  # type: ignore[union-attr]
    finally:
        second._release_lease()
        second._pool.shutdown(wait=False)


def test_released_lease_is_taken_immediately(client: SignedClient, env: Env) -> None:
    app: Any = client.app
    first = engine_for(client)
    second = TradingEngine(app.state.session_factory, app.state.broker_manager, live_locked=True)
    try:
        assert first.tick_once()
        first._release_lease()
        env.db.expire_all()
        assert env.db.get(SystemState, 1).engine_owner is None  # type: ignore[union-attr]
        assert second.tick_once()
        assert second.is_leader
    finally:
        second._release_lease()
        second._pool.shutdown(wait=False)
