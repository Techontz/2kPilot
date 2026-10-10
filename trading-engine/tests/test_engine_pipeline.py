"""End-to-end: paper broker → strategy → risk → execution → reconciliation → journal.

Creates the rows Laravel would write, then drives the trading engine
synchronously while stepping the simulated market.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.paper import PaperBroker
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment, TradingMode
from fxrobot.domain.trading import OrderStatus, SignalStatus, TradeStatus
from fxrobot.models import (
    Notification,
    Order,
    RiskProfile,
    Signal,
    StrategyEvaluation,
    SystemState,
    Trade,
    TradeEvent,
    TradingAccount,
    UserTradingState,
)
from fxrobot.trading_engine.context import load_controls
from fxrobot.trading_engine.engine import TradingEngine
from tests import factories
from tests.conftest import SignedClient

# Small windows → fast evaluations and plenty of signals on synthetic data.
FAST_PARAMS: dict[str, Any] = {
    "ema_fast": 10,
    "ema_slow": 30,
    "slope_lookback": 3,
    "pullback_zone_atr": 1.0,
    "max_extension_atr": 3.0,
    "confirmation": "trend_close",
}
LOOSE_RISK: dict[str, Any] = {
    "allowed_sessions": ["ASIA", "LONDON", "OVERLAP", "NEW_YORK"],
    "min_stop_pips": "1",
    "max_stop_pips": "500",
    "max_spread_pips": "10",
    "min_reward_risk": "1.0",
    "max_trades_per_day": 50,
    "max_drawdown_pct": "50",
    "max_daily_loss_pct": "50",
    "max_weekly_loss_pct": "50",
    "cooldown_after_losses": None,
    "max_data_age_seconds": 100000,
}


def setup_trading(
    client: SignedClient, db: Session, *, risk: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Rows as Laravel writes them: paper account, risk profile, enabled
    assignment (Laravel creates assignments PAUSED; the test enables it), resume."""
    account = factories.paper_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **(risk or LOOSE_RISK)))
    version = factories.strategy_version(db, **FAST_PARAMS)
    assignment = factories.assignment(db, account, version)
    factories.resume_trading(db)
    return {
        "account": {"id": str(account.id), "connection_id": str(account.connection_id)},
        "assignment": {"id": str(assignment.id)},
        "version": {"id": str(version.id)},
    }


def engine_for(client: SignedClient) -> TradingEngine:
    app: Any = client.app
    return app.state.trading_engine


def paper_broker(client: SignedClient, connection_id: str) -> PaperBroker:
    app: Any = client.app
    adapter = app.state.broker_manager.get(uuid.UUID(connection_id))
    assert isinstance(adapter, PaperBroker)
    return adapter


def run_until(
    client: SignedClient, connection_id: str, db: Session, predicate: Any, max_bars: int = 2000
) -> None:
    """Advance one M15 bar (15 one-minute bars) per engine tick — like the live
    engine, which ticks every couple of seconds and stops at each close of the
    strategy's timeframe, so signals are evaluated right after bars close."""
    engine = engine_for(client)
    broker = paper_broker(client, connection_id)
    for i in range(max_bars):
        broker.step(15)
        engine.tick_once()
        if i % 4 == 0:
            db.expire_all()
            if predicate():
                return
    raise AssertionError("condition not reached")


@pytest.fixture
def trading(client: SignedClient, db: Session) -> dict[str, Any]:
    return setup_trading(client, db)


def test_full_pipeline_produces_journaled_paper_trades(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    account_id = uuid.UUID(trading["account"]["id"])
    connection_id = trading["account"]["connection_id"]

    def closed_trade_exists() -> bool:
        return (
            db.scalar(
                select(func.count()).where(
                    Trade.account_id == account_id, Trade.status == TradeStatus.CLOSED
                )
            )
            > 0
        )

    run_until(client, connection_id, db, closed_trade_exists)

    signals = list(db.scalars(select(Signal).where(Signal.account_id == account_id)))
    assert signals, "strategy produced no signals"
    executed = [s for s in signals if s.status is SignalStatus.EXECUTED]
    assert executed
    for s in signals:
        assert s.reasons, "every signal records why it was generated"
        if s.status in (SignalStatus.EXECUTED, SignalStatus.REJECTED):
            assert s.risk_checks, "every decision records the risk checks"
        if s.status is SignalStatus.REJECTED:
            assert s.rejection_reason and s.rejection_reason.startswith("Trade rejected:")

    trade = db.scalars(
        select(Trade).where(Trade.account_id == account_id, Trade.status == TradeStatus.CLOSED)
    ).first()
    assert trade is not None
    assert trade.is_simulated
    assert trade.exit_reason is not None and trade.net_pnl is not None
    assert trade.stop_loss is not None and trade.initial_stop_loss is not None
    assert trade.risk_amount and trade.risk_amount > 0
    assert trade.session in {"ASIA", "LONDON", "OVERLAP", "NEW_YORK"}

    orders = list(db.scalars(select(Order).where(Order.account_id == account_id)))
    assert all(o.is_simulated for o in orders)
    assert all(len(o.client_order_id) == 24 for o in orders)
    assert {OrderStatus.FILLED} >= {o.status for o in orders if o.trade_id == trade.id}

    events = [
        e.event_type
        for e in db.scalars(
            select(TradeEvent)
            .where(TradeEvent.signal_id == trade.signal_id)
            .order_by(TradeEvent.id)
        )
    ]
    assert events[:5] == [
        "SIGNAL_GENERATED",
        "RISK_APPROVED",
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "POSITION_OPENED",
    ]
    closing = db.scalar(
        select(TradeEvent).where(
            TradeEvent.trade_id == trade.id, TradeEvent.event_type == "POSITION_CLOSED"
        )
    )
    assert closing is not None and "PAPER" in closing.message

    evaluations = db.scalar(select(func.count()).select_from(StrategyEvaluation))
    assert evaluations and evaluations > len(signals), "no-setup bars are also explained"
    kinds = {n.type for n in db.scalars(select(Notification))}
    assert {"signal.generated", "order.submitted", "position.opened"} <= kinds


def test_kill_switch_stops_strategy_evaluation(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    factories.stop_trading(db)
    broker = paper_broker(client, trading["account"]["connection_id"])
    engine = engine_for(client)
    for _ in range(120):
        broker.step(1)
        engine.tick_once()
    assert db.scalar(select(func.count()).select_from(StrategyEvaluation)) == 0
    assert db.scalar(select(func.count()).select_from(Signal)) == 0


def _tick_details(client: SignedClient) -> dict[uuid.UUID, str]:
    return {r.account_id: r.detail for r in engine_for(client).tick_once()}


def test_another_users_stop_never_stops_my_account(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    mine = uuid.UUID(trading["account"]["id"])
    other = factories.make_user(db)
    theirs = factories.paper_account(db, owner=other)
    factories.enable_account(db, theirs, factories.risk_profile(db, owner=other, **LOOSE_RISK))
    # The other user starts stopped (as after sign-up): only their account is held.
    details = _tick_details(client)
    assert details[mine] == "ok"
    assert details[theirs.id] == "monitoring (trading stopped)"
    factories.resume_trading(db, other)
    factories.stop_trading(db)  # now the default user stops; the other keeps trading
    details = _tick_details(client)
    assert details[mine] == "monitoring (trading stopped)"
    assert details[theirs.id] == "ok"


def test_platform_halt_stops_every_users_account(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    factories.halt_platform(db)
    broker = paper_broker(client, trading["account"]["connection_id"])
    for _ in range(120):
        broker.step(1)
        results = engine_for(client).tick_once()
    assert "halted platform-wide" in results[0].detail
    assert db.scalar(select(func.count()).select_from(StrategyEvaluation)) == 0
    factories.halt_platform(db, halted=False)
    assert _tick_details(client)[uuid.UUID(trading["account"]["id"])] == "ok"


def test_accounts_trade_only_in_their_owners_mode(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    account_id = uuid.UUID(trading["account"]["id"])
    # LIVE mode trades LIVE accounts only — never this PAPER account.
    factories.stop_trading(db)
    factories.set_mode(db, TradingMode.LIVE, authorized=True)
    factories.resume_trading(db)
    assert _tick_details(client)[account_id] == (
        "monitoring (PAPER account not traded in LIVE mode)"
    )
    # A LIVE account in LIVE mode still needs the server lock off and the authorisation.
    account = db.get(TradingAccount, account_id)
    assert account is not None
    account.environment = AccountEnvironment.LIVE
    db.commit()
    assert "LIVE hard lock" in _tick_details(client)[account_id]
    app: Any = client.app
    app.state.trading_engine.runner.live_locked = False
    factories.set_mode(db, TradingMode.LIVE, authorized=False)
    assert "not been authorised" in _tick_details(client)[account_id]
    factories.set_mode(db, TradingMode.LIVE, authorized=True, account=account)
    assert _tick_details(client)[account_id] == "ok"


def test_live_authorization_is_bound_to_the_account_and_its_limits(
    db: Session, trading: dict[str, Any]
) -> None:
    """Real money needs an authorisation for THIS account, with THIS risk profile,
    as the profile stood when the owner authorised it."""
    account = db.get(TradingAccount, uuid.UUID(trading["account"]["id"]))
    assert account is not None
    account.environment = AccountEnvironment.LIVE
    db.commit()
    mismatch = "Real-money authorization doesn't cover this account/limits — re-authorize"

    def blocked() -> str | None:
        db.expire_all()
        live = db.get(TradingAccount, account.id)
        assert live is not None
        return load_controls(db, live, live_locked=False).blocking_reason(live.environment)

    factories.set_mode(db, TradingMode.LIVE, authorized=False)
    assert "not been authorised" in (blocked() or "")
    # Authorised, but not for this account.
    factories.set_mode(db, TradingMode.LIVE, authorized=True)
    detail = blocked() or ""
    assert mismatch in detail and "another account" in detail

    factories.set_mode(db, TradingMode.LIVE, authorized=True, account=account)
    assert blocked() is None

    # The limits were edited after the authorisation.
    db.execute(update(UserTradingState).values(live_authorized_at=utcnow() - timedelta(minutes=1)))
    profile = db.get(RiskProfile, account.risk_profile_id)
    assert profile is not None
    profile.max_open_positions = 5  # updated_at moves to now
    db.commit()
    detail = blocked() or ""
    assert mismatch in detail and "edited" in detail

    # Re-authorised, then a different profile is assigned to the account.
    factories.set_mode(db, TradingMode.LIVE, authorized=True, account=account)
    assert blocked() is None
    other = factories.risk_profile(db, **LOOSE_RISK)
    account.risk_profile_id = other.id
    db.commit()
    detail = blocked() or ""
    assert mismatch in detail and "risk profile was changed" in detail


def test_disabled_account_is_monitored_but_never_traded(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    account = db.get(TradingAccount, uuid.UUID(trading["account"]["id"]))
    assert account is not None
    account.trading_enabled = False
    db.commit()
    broker = paper_broker(client, trading["account"]["connection_id"])
    for _ in range(200):
        broker.step(1)
        results = engine_for(client).tick_once()
    assert results[0].detail == "monitoring (trading disabled for this account)"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(StrategyEvaluation)) == 0
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_broker_disconnect_is_detected_and_blocks_trading(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    app: Any = client.app
    connection_id = uuid.UUID(trading["account"]["connection_id"])
    paper_broker(client, str(connection_id))
    app.state.broker_manager.faults[connection_id].disconnected = True
    results = engine_for(client).tick_once()
    assert results and not results[0].ok
    db.expire_all()
    kinds = {n.type for n in db.scalars(select(Notification))}
    assert "broker.disconnected" in kinds
    account = db.get(TradingAccount, uuid.UUID(trading["account"]["id"]))
    assert account is not None
    assert db.scalar(select(func.count()).select_from(Order)) == 0
    # Recovery: the fault clears, the manager reconnects after backoff.
    app.state.broker_manager.faults[connection_id].disconnected = False
    app.state.broker_manager._entries[connection_id].next_attempt = 0
    results = engine_for(client).tick_once()
    assert results[0].ok
    db.expire_all()
    assert "broker.reconnected" in {n.type for n in db.scalars(select(Notification))}


def test_engine_heartbeat_is_written(
    client: SignedClient, db: Session, trading: dict[str, Any]
) -> None:
    engine_for(client).tick_once()
    db.expire_all()
    state = db.get(SystemState, 1)
    assert state is not None and state.engine_heartbeat_at is not None
    assert state.engine_degraded is False
    health = client.get("/internal/health").json()
    assert health["engine_heartbeat_at"] is not None
