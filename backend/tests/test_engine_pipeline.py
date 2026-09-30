"""End-to-end: paper broker → strategy → risk → execution → reconciliation → journal.

Uses the real API to create the paper connection, then drives the trading
engine synchronously while stepping the simulated market.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.paper import PaperBroker
from fxrobot.domain.trading import OrderStatus, SignalStatus, TradeStatus
from fxrobot.models import (
    Notification,
    Order,
    Signal,
    StrategyEvaluation,
    Trade,
    TradeEvent,
    TradingAccount,
)
from fxrobot.trading_engine.engine import TradingEngine

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


def create_paper_account(client: TestClient, **settings: Any) -> dict[str, Any]:
    body = {
        "connector_type": "paper",
        "expected_environment": "PAPER",
        "label": "Test paper",
        "settings": {
            "price_source": "synthetic",
            "symbols": "EURUSD,USDJPY",
            "seconds_per_bar": 0,  # tests step the market manually
            "start_days_ago": 300,
            "seed": 3,
            **settings,
        },
    }
    response = client.post("/api/v1/brokers/connections", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def setup_trading(client: TestClient, *, risk: dict[str, Any] | None = None) -> dict[str, Any]:
    account = create_paper_account(client)
    profile = client.post(
        "/api/v1/risk/profiles",
        json={"name": f"test-{uuid.uuid4().hex[:6]}", "limits": risk or LOOSE_RISK},
    )
    assert profile.status_code == 201, profile.text
    patched = client.patch(
        f"/api/v1/accounts/{account['id']}",
        json={"risk_profile_id": profile.json()["id"], "trading_enabled": True},
    )
    assert patched.status_code == 200, patched.text
    strategy = client.get("/api/v1/strategies").json()[0]
    version = client.post(
        f"/api/v1/strategies/{strategy['id']}/versions",
        json={
            "parameters": {**strategy["versions"][0]["parameters"], **FAST_PARAMS},
            "notes": "fast",
        },
    ).json()
    assignment = client.post(
        "/api/v1/strategies/assignments",
        json={
            "strategy_version_id": version["id"],
            "account_id": account["id"],
            "symbol": "EURUSD",
        },
    ).json()
    assert assignment["status"] == "PAUSED"  # never trades merely because it was created
    enabled = client.post(f"/api/v1/strategies/assignments/{assignment['id']}/enable")
    assert enabled.status_code == 200, enabled.text
    client.post("/api/v1/trading/resume", json={"confirm": True})
    return {"account": account, "assignment": enabled.json(), "version": version}


def engine_for(client: TestClient) -> TradingEngine:
    app: Any = client.app
    return app.state.trading_engine


def paper_broker(client: TestClient, connection_id: str) -> PaperBroker:
    app: Any = client.app
    adapter = app.state.broker_manager.get(uuid.UUID(connection_id))
    assert isinstance(adapter, PaperBroker)
    return adapter


def run_until(
    client: TestClient, connection_id: str, db: Session, predicate: Any, max_bars: int = 2000
) -> None:
    """Advance one M15 bar per engine tick — like the live engine, which ticks
    every couple of seconds, so signals are evaluated right after bars close."""
    engine = engine_for(client)
    broker = paper_broker(client, connection_id)
    for i in range(max_bars):
        broker.step(1)
        engine.tick_once()
        if i % 4 == 0:
            db.expire_all()
            if predicate():
                return
    raise AssertionError("condition not reached")


@pytest.fixture
def trading(owner_client: TestClient) -> dict[str, Any]:
    return setup_trading(owner_client)


def test_full_pipeline_produces_journaled_paper_trades(
    owner_client: TestClient, db: Session, trading: dict[str, Any]
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

    run_until(owner_client, connection_id, db, closed_trade_exists)

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

    lifecycle = owner_client.get(f"/api/v1/trades/{trade.id}").json()
    assert lifecycle["signal"]["reasons"]
    assert lifecycle["evaluation"]["checks"]
    assert lifecycle["events"][0]["event_type"] == "SIGNAL_GENERATED"

    perf = owner_client.get(f"/api/v1/analytics/performance?account_id={account_id}").json()
    assert perf["has_data"] is True and perf["trades"] >= 1
    assert perf["simulated"] is True


def test_kill_switch_stops_strategy_evaluation(
    owner_client: TestClient, db: Session, trading: dict[str, Any]
) -> None:
    owner_client.post("/api/v1/trading/stop", json={"reason": "test"})
    broker = paper_broker(owner_client, trading["account"]["connection_id"])
    engine = engine_for(owner_client)
    for _ in range(120):
        broker.step(1)
        engine.tick_once()
    assert db.scalar(select(func.count()).select_from(StrategyEvaluation)) == 0
    assert db.scalar(select(func.count()).select_from(Signal)) == 0


def test_disabled_account_signals_are_rejected_by_risk(
    owner_client: TestClient, db: Session, trading: dict[str, Any]
) -> None:
    account_id = trading["account"]["id"]
    owner_client.patch(f"/api/v1/accounts/{account_id}", json={"trading_enabled": False})
    run_until(
        owner_client,
        trading["account"]["connection_id"],
        db,
        lambda: db.scalar(select(func.count()).select_from(Signal)) > 0,
    )
    signal = db.scalars(select(Signal)).first()
    assert signal is not None
    assert signal.status is SignalStatus.REJECTED
    assert "Account trading enabled" in (signal.rejection_reason or "")
    assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_broker_disconnect_is_detected_and_blocks_trading(
    owner_client: TestClient, db: Session, trading: dict[str, Any]
) -> None:
    app: Any = owner_client.app
    connection_id = uuid.UUID(trading["account"]["connection_id"])
    paper_broker(owner_client, str(connection_id))
    app.state.broker_manager.faults[connection_id].disconnected = True
    results = engine_for(owner_client).tick_once()
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
    results = engine_for(owner_client).tick_once()
    assert results[0].ok
    db.expire_all()
    assert "broker.reconnected" in {n.type for n in db.scalars(select(Notification))}


def test_engine_heartbeat_reports_running(
    owner_client: TestClient, trading: dict[str, Any]
) -> None:
    engine_for(owner_client).tick_once()
    status = owner_client.get("/api/v1/trading/status").json()
    assert status["engine_state"] == "running"
    assert status["new_orders_permitted"] is True
