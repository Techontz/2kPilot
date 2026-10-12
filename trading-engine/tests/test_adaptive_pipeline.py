"""Adaptive Trend & Momentum and the strategy emergency stop inside the live
pipeline (paper broker → runner → risk engine), on SYNTHETIC paper prices."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.db.types import utcnow
from fxrobot.domain.contracts import ContractFamily
from fxrobot.domain.trading import ExitReason, SignalStatus, TradeStatus
from fxrobot.models import Signal, Strategy, StrategyEvaluation, StrategyVersion, Trade
from fxrobot.services.strategies import ensure_builtin_strategies
from fxrobot.trading_engine.context import strategy_stop_reason
from tests import factories
from tests.conftest import SignedClient
from tests.test_engine_pipeline import (
    LOOSE_RISK,
    engine_for,
    paper_broker,
    run_until,
    setup_trading,
)


def adaptive_version(db: Session, **params: Any) -> StrategyVersion:
    ensure_builtin_strategies(db)
    strategy = db.scalars(
        select(Strategy).where(
            Strategy.key == "adaptive_trend_momentum", Strategy.user_id.is_(None)
        )
    ).one()
    base = strategy.versions[0]
    version = StrategyVersion(
        strategy_id=strategy.id,
        version=base.version + 1,
        code_version=base.code_version,
        parameters={**base.parameters, **params},
        notes="test",
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    return version


def test_the_builtin_is_registered_once_with_its_details(db: Session) -> None:
    ensure_builtin_strategies(db)
    ensure_builtin_strategies(db)  # idempotent
    rows = list(db.scalars(select(Strategy).where(Strategy.key == "adaptive_trend_momentum")))
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Adaptive Trend & Momentum" and row.user_id is None
    assert row.slug == "adaptive-trend-momentum" and row.source == "template"
    assert row.description.startswith("Uses trend, momentum, and volatility filters")
    assert row.details and row.details["supported_contract_families"] == ["SPOT", "MULTIPLIER"]
    assert row.versions[0].parameters["min_adx"] == 25.0


def test_emergency_stop_blocks_new_entries_and_never_closes_positions(
    client: SignedClient, db: Session
) -> None:
    trading = setup_trading(client, db)
    account_id = uuid.UUID(trading["account"]["id"])
    connection_id = trading["account"]["connection_id"]
    version = db.get(StrategyVersion, uuid.UUID(trading["version"]["id"]))
    assert version is not None

    def open_trade() -> bool:
        return bool(
            db.scalar(
                select(func.count()).where(
                    Trade.account_id == account_id, Trade.status == TradeStatus.OPEN
                )
            )
        )

    run_until(client, connection_id, db, open_trade)
    held = db.scalars(
        select(Trade).where(Trade.account_id == account_id, Trade.status == TradeStatus.OPEN)
    ).first()
    assert held is not None
    strategy = version.strategy
    strategy.entries_disabled_at = utcnow()
    strategy.entries_disabled_reason = "suspicious fills under review"
    db.commit()
    signals_before = db.scalar(select(func.count()).select_from(Signal)) or 0

    def new_signal() -> bool:
        return (db.scalar(select(func.count()).select_from(Signal)) or 0) > signals_before

    run_until(client, connection_id, db, new_signal)
    db.expire_all()
    fresh = list(db.scalars(select(Signal).order_by(Signal.created_at)))[signals_before:]
    assert fresh and all(s.status is SignalStatus.REJECTED for s in fresh)
    assert all("suspicious fills under review" in (s.rejection_reason or "") for s in fresh)
    assert all("Strategy enabled" in (s.rejection_reason or "") for s in fresh)
    trade = db.get(Trade, held.id)
    assert trade is not None
    # The stop itself never closes anything: the position is still open, or was
    # closed by its own stop loss / take profit at the broker.
    assert trade.status is TradeStatus.OPEN or trade.exit_reason in (
        ExitReason.STOP_LOSS,
        ExitReason.TAKE_PROFIT,
    )


def test_a_stop_on_the_builtin_also_covers_users_copies(db: Session) -> None:
    builtin = Strategy(key="adaptive_trend_momentum", name="Built-in", description="")
    copy = Strategy(key="adaptive_trend_momentum", name="Mine", description="")
    copy.copied_from = builtin
    assert strategy_stop_reason(copy) is None
    builtin.entries_disabled_at = utcnow()
    builtin.entries_disabled_reason = "data feed issue"
    reason = strategy_stop_reason(copy)
    assert reason and "copied from Built-in" in reason and "data feed issue" in reason
    assert strategy_stop_reason(None) is None


def test_rise_fall_assignment_is_never_evaluated(client: SignedClient, db: Session) -> None:
    account = factories.paper_account(db, symbols="R_10")
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    version = adaptive_version(db)
    factories.assignment(
        db,
        account,
        version,
        symbol="R_10",
        contract_family=ContractFamily.RISE_FALL,
        duration=15,
        duration_unit="m",
    )
    factories.resume_trading(db)
    broker = paper_broker(client, str(account.connection_id))
    engine = engine_for(client)
    for _ in range(3):
        broker.step(5)
        engine.tick_once()
    db.expire_all()
    evaluations = list(db.scalars(select(StrategyEvaluation)))
    assert evaluations
    assert all(e.outcome == "NO_SETUP" for e in evaluations)
    assert "Rise/Fall" in evaluations[0].summary
    assert evaluations[0].checks[0]["name"] == "Supported market & contract"
    assert db.scalar(select(func.count()).select_from(Signal)) == 0


def test_unchecked_market_is_never_evaluated(client: SignedClient, db: Session) -> None:
    account = factories.paper_account(db, symbols="EURUSD")
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    factories.assignment(db, account, adaptive_version(db), symbol="EURUSD")
    factories.resume_trading(db)
    broker = paper_broker(client, str(account.connection_id))
    engine = engine_for(client)
    broker.step(5)
    engine.tick_once()
    db.expire_all()
    evaluation = db.scalars(select(StrategyEvaluation)).first()
    assert evaluation is not None and "R_10, R_25" in evaluation.summary


def test_adaptive_strategy_trades_paper_spot_through_the_risk_engine(
    client: SignedClient, db: Session
) -> None:
    """Signals on the SYNTHETIC paper R_10 feed reach the risk engine; the strategy's
    caps (one position) apply on top of the profile."""
    account = factories.paper_account(db, symbols="R_10")
    risk = {**LOOSE_RISK, "max_open_positions": 5, "risk_per_trade_pct": "1.0"}
    factories.enable_account(db, account, factories.risk_profile(db, **risk))
    # Looser filters so the short synthetic run produces signals quickly.
    version = adaptive_version(
        db, min_adx=15, sideways_adx=10, high_vol_percentile=100, pullback_atr_band=1.0
    )
    factories.assignment(db, account, version, symbol="R_10")
    factories.resume_trading(db)

    def decided() -> bool:
        return bool(
            db.scalar(
                select(func.count()).where(
                    Signal.account_id == account.id, Signal.status != SignalStatus.NEW
                )
            )
        )

    run_until(client, str(account.connection_id), db, decided, max_bars=3000)
    signal = db.scalars(select(Signal).where(Signal.status != SignalStatus.NEW)).first()
    assert signal is not None and signal.risk_checks
    rules = {c["rule"] for c in signal.risk_checks}
    assert {"Kill switch", "Strategy enabled", "Minimum balance", "Open positions"} <= rules
    if signal.status is SignalStatus.EXECUTED:
        trade = db.scalars(select(Trade).where(Trade.signal_id == signal.id)).one()
        assert trade.stop_loss is not None and trade.take_profit is not None
        # 1 % profile risk, capped to 0.5 % by the strategy.
        assert trade.risk_amount is not None
        assert trade.risk_amount <= account.balance * 5 / 1000 + 1
    evaluations = list(db.scalars(select(StrategyEvaluation)))
    assert any(c["name"] == "Market regime" for e in evaluations for c in e.checks)
    assert timedelta(0) <= utcnow() - signal.created_at
