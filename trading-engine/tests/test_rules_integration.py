"""A `rules` strategy runs exactly like a code strategy: in the backtester
(entries, strategy exits, contracts) and in the live runner on a paper account
(evaluations explained in plain English, exit rules closing trades)."""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.backtesting.engine import BacktestConfig, Backtester, BacktestResult
from fxrobot.domain.contracts import ContractFamily, ContractSpec
from fxrobot.domain.market import Timeframe
from fxrobot.domain.trading import ExitReason, TradeStatus
from fxrobot.models import StrategyEvaluation, Trade
from tests import factories
from tests.conftest import SignedClient
from tests.test_backtesting import LOOSE, SYMBOL, SYN_END, SYN_START, synthetic
from tests.test_engine_pipeline import LOOSE_RISK, run_until


def ema(period: int) -> dict[str, Any]:
    return {"indicator": "ema", "params": {"period": period}}


def rsi_vs(op: str, value: float) -> dict[str, Any]:
    return {
        "left": {"indicator": "rsi", "params": {"period": 14}},
        "op": op,
        "right": {"value": value},
    }


CROSS_RULES: dict[str, Any] = {
    "timeframe": "M15",
    "entry": {
        "buy": {"all": [{"left": ema(5), "op": "crosses_above", "right": ema(13)}]},
        "sell": {"all": [{"left": ema(5), "op": "crosses_below", "right": ema(13)}]},
    },
    "exit": {
        "stop": {"type": "atr", "atr_period": 14, "multiple": 4},
        "target": {"type": "rr", "ratio": 4},  # far: most exits come from the exit rules
        "close_buy_when": {"any": [rsi_vs("gt", 60)]},
        "close_sell_when": {"any": [rsi_vs("lt", 40)]},
    },
}


def backtest(
    contract: ContractSpec | None = None, rules: dict[str, Any] | None = None
) -> BacktestResult:
    cfg = BacktestConfig(
        strategy_key="rules",
        params=rules or CROSS_RULES,
        symbol=SYMBOL,
        start=SYN_START,
        end=SYN_END,
        initial_capital=Decimal(10000),
        limits=LOOSE,
        contract=contract or ContractSpec(),
    )
    return Backtester(cfg, synthetic(), Timeframe.M15).run()


def test_backtest_spot_with_strategy_exits_is_deterministic() -> None:
    a, b = backtest(), backtest()
    assert a.trades, "the rule set produced no trades"
    reasons = {t.exit_reason for t in a.trades}
    assert ExitReason.STRATEGY in reasons
    assert a.metrics["strategy_exits"] > 0
    assert [(t.entry_time, t.exit_time, t.net_pnl) for t in a.trades] == [
        (t.entry_time, t.exit_time, t.net_pnl) for t in b.trades
    ]
    for t in a.trades:
        assert t.stop_loss is not None and t.reasons
        if t.exit_reason is ExitReason.STRATEGY:
            assert t.exit_time is not None and t.exit_time > t.entry_time


def test_backtest_rise_fall_ignores_exit_rules() -> None:
    spec = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=45, duration_unit="m")
    result = backtest(spec)
    assert result.trades
    assert {t.exit_reason for t in result.trades} == {ExitReason.EXPIRED}
    assert all(t.outcome in ("WON", "LOST") for t in result.trades)


def test_backtest_multiplier_strategy_exit_sells_the_contract() -> None:
    spec = ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=50)
    result = backtest(spec)
    sold = [t for t in result.trades if t.exit_reason is ExitReason.STRATEGY]
    assert sold and all(t.outcome == "SOLD" for t in sold)
    assert all(t.net_pnl >= -(t.stake or 0) for t in result.trades)


def test_backtest_without_exit_rules_has_no_strategy_exits() -> None:
    rules = {**CROSS_RULES, "exit": {"stop": {"type": "atr", "atr_period": 14, "multiple": 2}}}
    result = backtest(rules=rules)
    assert result.trades and "strategy_exits" not in result.metrics
    assert ExitReason.STRATEGY not in {t.exit_reason for t in result.trades}


def test_live_runner_trades_and_exits_a_rules_strategy(client: SignedClient, db: Session) -> None:
    account = factories.paper_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    version = factories.rules_version(db, CROSS_RULES)
    assignment = factories.assignment(db, account, version)
    factories.resume_trading(db)

    def strategy_exit_happened() -> bool:
        return (
            db.scalar(
                select(func.count()).where(
                    Trade.account_id == account.id,
                    Trade.status == TradeStatus.CLOSED,
                    Trade.exit_reason == ExitReason.STRATEGY,
                )
            )
            > 0
        )

    run_until(client, str(account.connection_id), db, strategy_exit_happened, max_bars=3000)

    trade = db.scalars(select(Trade).where(Trade.exit_reason == ExitReason.STRATEGY)).first()
    assert trade is not None and trade.strategy_version_id == version.id
    evaluations = list(
        db.scalars(
            select(StrategyEvaluation).where(StrategyEvaluation.assignment_id == assignment.id)
        )
    )
    assert evaluations
    details = [c["detail"] for e in evaluations for c in e.checks]
    assert any("EMA 5" in d and ("✓" in d or "✗" in d) for d in details)
    assert uuid.UUID(str(assignment.id))


def _template(slug: str) -> dict[str, Any]:
    import json

    from tests.conftest import BACKEND_DIR

    path = BACKEND_DIR / "database" / "data" / "strategy_templates.json"
    templates = json.loads(path.read_text())["templates"]
    return next(t for t in templates if t["slug"] == slug)


def test_m5_template_evaluates_every_candle_and_opens_a_paper_trade(
    client: SignedClient, db: Session, monkeypatch: Any
) -> None:
    """The built-in EMA crossover template decides on M5 candles. A Paper account
    fast-forwarding at its normal pace (15 simulated minutes per 2 s) must stop at
    every M5 close, evaluate that candle, and trade when the rules fire."""
    from datetime import timedelta

    from tests.test_engine_pipeline import engine_for, paper_broker

    rules = _template("ema-crossover")["rules"]
    assert rules["timeframe"] == "M5"
    account = factories.paper_account(db, seconds_per_bar=2)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    version = factories.rules_version(db, rules)
    assignment = factories.assignment(db, account, version)
    factories.resume_trading(db)
    engine = engine_for(client)
    broker = paper_broker(client, str(account.connection_id))
    wall = [0.0]
    monkeypatch.setattr(broker.market, "_wall", lambda: wall[0])
    broker.market._last_step_wall = 0.0
    start = broker.now()
    assert start.minute % 5 == 0

    def trades() -> int:
        db.expire_all()
        return int(db.scalar(select(func.count()).where(Trade.account_id == account.id)) or 0)

    ticks = 0
    while trades() == 0:
        ticks += 1
        assert ticks <= 300, "the template never traded"
        wall[0] += 2.0  # one engine tick of wall time: up to 15 simulated minutes
        engine.tick_once()
        assert broker.now() == start + timedelta(minutes=5 * ticks)  # held at each M5 close

    evaluations = list(
        db.scalars(
            select(StrategyEvaluation)
            .where(StrategyEvaluation.assignment_id == assignment.id)
            .order_by(StrategyEvaluation.bar_time)
        )
    )
    times = [e.bar_time for e in evaluations]
    assert len(times) == ticks  # one evaluation per M5 candle, none skipped
    assert all(b - a == timedelta(minutes=5) for a, b in itertools.pairwise(times))
    assert "INSUFFICIENT_DATA" not in {e.outcome for e in evaluations}
    trade = db.scalars(select(Trade).where(Trade.account_id == account.id)).one()
    assert trade.strategy_version_id == version.id and trade.symbol == "EURUSD"
