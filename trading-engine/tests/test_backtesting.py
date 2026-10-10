"""Backtesting: look-ahead / data-leakage guards, fill & exit realism, costs,
determinism, metrics, and the BacktestService modes through the API."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.analytics import metrics
from fxrobot.backtesting.engine import (
    BacktestConfig,
    Backtester,
    BacktestError,
    BacktestResult,
    CostModel,
    SimTrade,
)
from fxrobot.backtesting.service import list_backtests
from fxrobot.domain.market import Candle, Side, Timeframe
from fxrobot.domain.trading import DataSource, ExitReason
from fxrobot.market_data import store
from fxrobot.market_data.resample import resample
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries
from fxrobot.models import Backtest, BacktestTrade, Dataset, Notification
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.strategy_engine import registry
from fxrobot.strategy_engine.base import (
    Evaluation,
    MarketView,
    Outcome,
    SignalIntent,
    Strategy,
)
from fxrobot.strategy_engine.trend_pullback import TrendPullbackV1
from tests import factories
from tests.conftest import SignedClient

SPEC = DEFAULT_SPECS["EURUSD"]
SYMBOL = SPEC.symbol_info()
LOOSE = RiskLimits.from_mapping(
    {
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
    }
)
FAST_M15: dict[str, Any] = {
    "entry_timeframe": "M15",
    "higher_timeframe": "H1",
    "ema_fast": 10,
    "ema_slow": 30,
    "slope_lookback": 3,
    "pullback_zone_atr": 1.0,
    "max_extension_atr": 3.0,
    "confirmation": "trend_close",
}
FAST_H1 = {**FAST_M15, "entry_timeframe": "H1", "higher_timeframe": "H4"}
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)  # Monday
SYN_START = ORIGIN + timedelta(days=5)
SYN_END = ORIGIN + timedelta(days=40)
NO_COSTS = CostModel(
    spread_pips=Decimal(0), commission_per_lot=Decimal(0), slippage_pips=Decimal(0)
)
W = datetime(2025, 3, 5, tzinfo=UTC)  # Wednesday 00:00 UTC


# ── helpers ──────────────────────────────────────────────────────────────


def synthetic(days: int = 40, seed: int = 11) -> list[Candle]:
    return SyntheticSeries(SPEC, seed, ORIGIN, Timeframe.M15).bars(
        ORIGIN, ORIGIN + timedelta(days=days)
    )


def run(
    candles: list[Candle],
    *,
    key: str = "trend_pullback",
    params: dict[str, Any] | None = None,
    start: datetime = SYN_START,
    end: datetime = SYN_END,
    costs: CostModel | None = None,
    base_tf: Timeframe = Timeframe.M15,
    limits: RiskLimits = LOOSE,
) -> BacktestResult:
    cfg = BacktestConfig(
        strategy_key=key,
        params=FAST_M15 if params is None else params,
        symbol=SYMBOL,
        start=start,
        end=end,
        initial_capital=Decimal(10000),
        limits=limits,
        costs=costs or CostModel(),
    )
    return Backtester(cfg, candles, base_tf).run()


def entry_fields(t: SimTrade) -> tuple[Any, ...]:
    return (
        t.side,
        t.signal_time,
        t.entry_time,
        t.entry_price,
        t.volume,
        t.stop_loss,
        t.take_profit,
        t.risk_amount,
    )


def spike(candles: list[Candle], after: datetime) -> list[Candle]:
    """Wildly distort every bar at/after `after` (the 'future')."""
    out = []
    for c in candles:
        if c.time < after:
            out.append(c)
        else:
            o, cl = c.open * Decimal("1.3"), c.close * Decimal("0.7")
            out.append(
                Candle(
                    c.time,
                    o,
                    max(o, cl) * Decimal("1.05"),
                    min(o, cl) * Decimal("0.95"),
                    cl,
                    c.tick_volume,
                    (c.spread_points or 0) * 5,
                )
            )
    return out


class RecordingTrendPullback(TrendPullbackV1):
    """The real strategy, logging every decision it makes."""

    key: ClassVar[str] = "recording_tp"

    def __init__(self) -> None:
        self.log: list[tuple[datetime | None, Outcome, SignalIntent | None]] = []

    def evaluate(self, view: MarketView, params: Any) -> Evaluation:
        result = super().evaluate(view, params)
        self.log.append((getattr(view, "now", None), result.outcome, result.signal))
        return result


class ProbeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_timeframe: Timeframe = Timeframe.H1
    higher_timeframe: Timeframe = Timeframe.H4


@dataclass
class Script:
    side: Side
    stop: Decimal
    target: Decimal | None


class ProbeStrategy(Strategy):
    """A strategy stub that tries to peek at every timeframe (including ones it
    never declared) and emits scripted signals at chosen decision times."""

    key: ClassVar[str] = "probe"
    name: ClassVar[str] = "Probe"
    code_version: ClassVar[str] = "0"
    description: ClassVar[str] = "test stub"
    Params = ProbeParams

    def __init__(self, script: dict[datetime, Script] | None = None) -> None:
        self.script = script or {}
        self.calls: list[datetime] = []
        self.violations: list[str] = []
        self.latest: list[dict[Timeframe, datetime | None]] = []

    def timeframes(self, params: Any) -> tuple[Timeframe, ...]:
        return (params.entry_timeframe, params.higher_timeframe)

    def required_bars(self, params: Any) -> dict[Timeframe, int]:
        return {params.entry_timeframe: 1, params.higher_timeframe: 1}

    def evaluate(self, view: MarketView, params: Any) -> Evaluation:
        now: datetime = view.now  # type: ignore[attr-defined]
        self.calls.append(now)
        latest: dict[Timeframe, datetime | None] = {}
        for tf in Timeframe:
            bars = list(view.candles(tf))
            latest[tf] = bars[-1].time if bars else None
            leaked = [c.time for c in bars if c.time + tf.delta > now]
            if leaked:
                self.violations.append(f"{tf} at {now}: {leaked}")
        self.latest.append(latest)
        entry = list(view.candles(params.entry_timeframe))
        plan = self.script.get(now)
        if plan is None or not entry:
            return Evaluation(Outcome.NO_SETUP, "probe", entry[-1].time if entry else None)
        signal = SignalIntent(
            side=plan.side,
            timeframe=params.entry_timeframe,
            bar_time=entry[-1].time,
            entry_price=entry[-1].close,
            stop_loss=plan.stop,
            take_profit=plan.target,
            reasons=["scripted"],
        )
        return Evaluation(Outcome.SIGNAL, "scripted", entry[-1].time, [], signal)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProbeStrategy]:
    stub = ProbeStrategy()
    monkeypatch.setitem(registry._STRATEGIES, stub.key, stub)
    yield stub


def flat_h1(
    n: int = 30,
    price: str = "1.10000",
    overrides: dict[int, tuple[str, str, str, str]] | None = None,
) -> list[Candle]:
    """Flat H1 bars from Wednesday 00:00; overrides[i] = (open, high, low, close)."""
    out = []
    for i in range(n):
        o, h, lo, c = (overrides or {}).get(i, (price, price, price, price))
        out.append(
            Candle(W + timedelta(hours=i), Decimal(o), Decimal(h), Decimal(lo), Decimal(c), 1, 10)
        )
    return out


BUY_PLAN = Script(Side.BUY, Decimal("1.09800"), Decimal("1.10400"))
SELL_PLAN = Script(Side.SELL, Decimal("1.10200"), Decimal("1.09600"))
SIGNAL_AT = W + timedelta(hours=10)  # decision when the 09:00 bar closes
ENTRY_BAR = {10: ("1.10100", "1.10150", "1.10050", "1.10100")}
COSTS = CostModel(
    spread_pips=Decimal(1), commission_per_lot=Decimal(0), slippage_pips=Decimal("0.2")
)


def scripted(
    probe: ProbeStrategy,
    bars: list[Candle],
    plan: Script = BUY_PLAN,
    costs: CostModel = COSTS,
    at: datetime = SIGNAL_AT,
) -> BacktestResult:
    probe.script = {at: plan}
    return run(
        bars,
        key="probe",
        params={},
        start=W,
        end=W + timedelta(hours=len(bars)),
        costs=costs,
        base_tf=Timeframe.H1,
    )


# ── synthetic reference runs (computed once) ─────────────────────────────


@pytest.fixture(scope="module")
def candles() -> list[Candle]:
    return synthetic()


@pytest.fixture(scope="module")
def recorded(candles: list[Candle]) -> Iterator[tuple[BacktestResult, RecordingTrendPullback]]:
    strategy = RecordingTrendPullback()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(registry._STRATEGIES, strategy.key, strategy)
        yield run(candles, key=strategy.key), strategy


@pytest.fixture(scope="module")
def baseline(recorded: tuple[BacktestResult, RecordingTrendPullback]) -> BacktestResult:
    return recorded[0]


def test_reference_run_is_meaningful(baseline: BacktestResult) -> None:
    assert len(baseline.trades) >= 10, "reference run must trade enough to test leakage"
    reasons = {t.exit_reason for t in baseline.trades}
    assert {ExitReason.STOP_LOSS, ExitReason.TAKE_PROFIT} <= reasons
    assert baseline.metrics["trades"] == len(baseline.trades)
    assert baseline.signals >= len(baseline.trades)


# ── look-ahead / data leakage ────────────────────────────────────────────


@pytest.mark.parametrize("cut_days", [14, 23, 31])
@pytest.mark.parametrize("variant", ["data_ends", "config_ends"])
def test_truncation_invariance(
    candles: list[Candle], baseline: BacktestResult, cut_days: int, variant: str
) -> None:
    """Everything decided before T is identical whether history stops at T or continues."""
    cut = ORIGIN + timedelta(days=cut_days, hours=13, minutes=45)
    data = [c for c in candles if c.time < cut] if variant == "data_ends" else candles
    short = run(data, end=cut)
    finished = [t for t in short.trades if t.exit_reason is not ExitReason.END_OF_TEST]
    assert finished == [
        t for t in baseline.trades if t.exit_time is not None and t.exit_time <= cut
    ]
    assert [entry_fields(t) for t in short.trades] == [
        entry_fields(t) for t in baseline.trades if t.entry_time < cut
    ]
    open_at_cut = [t for t in short.trades if t.exit_reason is ExitReason.END_OF_TEST]
    assert len(open_at_cut) <= 1
    for t in open_at_cut:
        assert t.exit_time == cut  # closed at the last available bar, not a future one


def test_future_spikes_do_not_change_past_decisions(
    candles: list[Candle], recorded: tuple[BacktestResult, RecordingTrendPullback]
) -> None:
    baseline, reference = recorded
    cut = ORIGIN + timedelta(days=21, hours=9)
    strategy = RecordingTrendPullback()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(registry._STRATEGIES, strategy.key, strategy)
        spiked = run(spike(candles, cut), key=strategy.key)
    before = [e for e in reference.log if e[0] is not None and e[0] <= cut]
    assert len(before) > 1000
    assert [e for e in strategy.log if e[0] is not None and e[0] <= cut] == before
    assert [entry_fields(t) for t in spiked.trades if t.entry_time < cut] == [
        entry_fields(t) for t in baseline.trades if t.entry_time < cut
    ]
    assert [t for t in spiked.trades if t.exit_time and t.exit_time <= cut] == [
        t for t in baseline.trades if t.exit_time and t.exit_time <= cut
    ]
    # Sanity: the distortion really does change the future.
    assert [e for e in strategy.log if e[0] and e[0] > cut] != [
        e for e in reference.log if e[0] and e[0] > cut
    ]


def test_entries_fill_at_next_bar_open_not_signal_close(
    candles: list[Candle], baseline: BacktestResult
) -> None:
    by_time = {c.time: c for c in candles}
    slip = Decimal("0.2") * SYMBOL.pip_size
    for t in baseline.trades:
        assert t.entry_time == t.signal_time + Timeframe.M15.delta, t
        bar = by_time[t.entry_time]
        spread = Decimal(bar.spread_points or 0) * SYMBOL.point
        expected = bar.open + spread + slip if t.side is Side.BUY else bar.open - slip
        assert t.entry_price == expected
        assert t.entry_time > t.signal_time


def test_higher_entry_timeframe_fills_on_the_first_base_bar_after_close(
    candles: list[Candle],
) -> None:
    result = run(candles, params=FAST_H1)
    assert result.trades
    by_time = {c.time: c for c in candles}
    for t in result.trades:
        assert t.signal_time == Timeframe.H1.floor(t.signal_time)
        assert t.entry_time == t.signal_time + Timeframe.H1.delta
        assert t.entry_time in by_time


def test_scripted_fill_uses_next_open_plus_costs(probe: ProbeStrategy) -> None:
    result = scripted(probe, flat_h1(overrides=ENTRY_BAR))
    (trade,) = result.trades
    assert trade.signal_time == W + timedelta(hours=9)
    assert trade.entry_time == W + timedelta(hours=10)
    # 10:00 open 1.10100 + 1 pip spread + 0.2 pip slippage; NOT the 09:00 close (1.10000).
    assert trade.entry_price == Decimal("1.10112")
    assert trade.volume == Decimal("0.25")  # 0.5 % of 10 000 over a 20-pip stop


def test_higher_timeframe_visible_only_after_its_period_closes(
    probe: ProbeStrategy, candles: list[Candle]
) -> None:
    run(candles, key="probe", params={}, base_tf=Timeframe.M15)
    assert probe.calls, "the probe must have been evaluated"
    assert probe.violations == []
    h4_times = [c.time for c in resample(candles, Timeframe.H4)]
    for now, latest in zip(probe.calls, probe.latest, strict=True):
        h4 = latest[Timeframe.H4]
        assert h4 is not None and h4 + Timeframe.H4.delta <= now
        # ...and it is the most recently CLOSED H4 bar: no extra lag either.
        assert h4 == max(t for t in h4_times if t + Timeframe.H4.delta <= now)
        if Timeframe.H4.floor(now) == now and now - Timeframe.H4.delta in h4_times:
            assert h4 == now - Timeframe.H4.delta  # visible the moment it closes


def test_strategy_reading_future_only_sees_closed_bars(
    probe: ProbeStrategy, candles: list[Candle]
) -> None:
    run(candles, key="probe", params={"entry_timeframe": "H1", "higher_timeframe": "D1"})
    assert len(probe.calls) > 500
    assert probe.violations == []
    for now, latest in zip(probe.calls, probe.latest, strict=True):
        m15 = latest[Timeframe.M15]
        assert m15 is not None and m15 + Timeframe.M15.delta <= now
        # Timeframes the strategy never declared are simply unavailable.
        assert latest[Timeframe.M1] is None and latest[Timeframe.H4] is None
        assert now == Timeframe.H1.floor(now)  # decisions only when entry bars close


def test_signal_on_final_bar_never_fills(probe: ProbeStrategy) -> None:
    bars = flat_h1(12)
    result = scripted(probe, bars, at=W + timedelta(hours=12))
    assert result.signals == 1
    assert result.trades == []


# ── exits ────────────────────────────────────────────────────────────────


def test_bar_touching_stop_and_target_assumes_stop_first(probe: ProbeStrategy) -> None:
    bars = flat_h1(overrides={**ENTRY_BAR, 11: ("1.10100", "1.10500", "1.09700", "1.10300")})
    (trade,) = scripted(probe, bars).trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("1.09798")  # stop − 0.2 pip slippage
    assert trade.exit_time == W + timedelta(hours=12)  # when that bar closed
    assert trade.gross_pnl == Decimal("-78.50")


def test_sell_bar_touching_both_assumes_stop_first(probe: ProbeStrategy) -> None:
    bars = flat_h1(overrides={11: ("1.10000", "1.10300", "1.09400", "1.09500")})
    (trade,) = scripted(probe, bars, plan=SELL_PLAN).trades
    assert trade.side is Side.SELL
    assert trade.entry_price == Decimal("1.09998")  # sells fill at bid − slippage
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("1.10202")
    assert trade.gross_pnl == Decimal("-51.00")


def test_gap_through_stop_fills_at_the_worse_open(probe: ProbeStrategy) -> None:
    bars = flat_h1(overrides={**ENTRY_BAR, 11: ("1.09500", "1.09600", "1.09400", "1.09550")})
    (trade,) = scripted(probe, bars).trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == Decimal("1.09498")  # open − slippage, far beyond the stop
    assert trade.gross_pnl == Decimal("-153.50")
    assert trade.net_pnl < -trade.risk_amount  # gaps can lose more than planned


def test_take_profit_fills_at_target(probe: ProbeStrategy) -> None:
    bars = flat_h1(overrides={**ENTRY_BAR, 11: ("1.10100", "1.10450", "1.10050", "1.10400")})
    (trade,) = scripted(probe, bars).trades
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.exit_price == Decimal("1.10400")
    assert trade.gross_pnl == Decimal("72.00")
    assert trade.r_multiple == (trade.net_pnl / trade.risk_amount).quantize(Decimal("0.01"))


def test_gap_past_stop_before_entry_skips_the_trade(probe: ProbeStrategy) -> None:
    bars = flat_h1(overrides={10: ("1.09700", "1.09750", "1.09650", "1.09700")})
    result = scripted(probe, bars)
    assert result.trades == []
    assert result.rejections == {"Gap through stop before entry": 1}


def test_open_position_is_closed_at_end_of_test(probe: ProbeStrategy) -> None:
    bars = flat_h1(30, overrides=ENTRY_BAR)
    result = scripted(probe, bars)
    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.END_OF_TEST
    assert trade.exit_price == Decimal("1.10000")  # last close (bid for a long)
    assert trade.exit_time == W + timedelta(hours=30)
    assert result.metrics["trades"] == 1
    assert result.metrics["ending_balance"] == float(Decimal(10000) + trade.net_pnl)


def test_risk_rejections_are_counted(probe: ProbeStrategy) -> None:
    tight = RiskLimits.from_mapping({**LOOSE.as_json(), "min_stop_pips": "50"})
    probe.script = {SIGNAL_AT: BUY_PLAN}
    bars = flat_h1(overrides=ENTRY_BAR)
    result = run(
        bars,
        key="probe",
        params={},
        start=W,
        end=W + timedelta(hours=30),
        base_tf=Timeframe.H1,
        limits=tight,
    )
    assert result.trades == []
    assert result.signals == 1
    assert sum(result.rejections.values()) == 1


# ── costs ────────────────────────────────────────────────────────────────

TP_BARS = {**ENTRY_BAR, 11: ("1.10100", "1.10450", "1.10050", "1.10400")}


@pytest.mark.parametrize(
    "costs",
    [
        {"spread_pips": Decimal(2)},
        {"commission_per_lot": Decimal(7)},
        {"slippage_pips": Decimal(1)},
        {"spread_pips": Decimal(2), "commission_per_lot": Decimal(7), "slippage_pips": Decimal(1)},
    ],
)
def test_higher_costs_strictly_reduce_net_pnl(probe: ProbeStrategy, costs: dict[str, Any]) -> None:
    free = scripted(probe, flat_h1(overrides=TP_BARS), costs=NO_COSTS).trades[0]
    base = {
        "spread_pips": Decimal(0),
        "commission_per_lot": Decimal(0),
        "slippage_pips": Decimal(0),
    }
    costly = scripted(
        probe, flat_h1(overrides=TP_BARS), costs=CostModel(**{**base, **costs})
    ).trades[0]
    assert costly.net_pnl < free.net_pnl
    assert costly.volume == free.volume


def test_costs_monotonic_on_synthetic_data(candles: list[Candle]) -> None:
    cheap = run(candles, costs=NO_COSTS)
    dear = run(
        candles,
        costs=CostModel(
            spread_pips=Decimal(3), commission_per_lot=Decimal(10), slippage_pips=Decimal(1)
        ),
    )
    assert dear.metrics["net_pnl"] < cheap.metrics["net_pnl"]
    assert cheap.metrics["total_costs"] == 0
    assert dear.metrics["total_costs"] > 0


def test_commission_charged_per_side(probe: ProbeStrategy) -> None:
    costs = CostModel(
        spread_pips=Decimal(0), commission_per_lot=Decimal(4), slippage_pips=Decimal(0)
    )
    (trade,) = scripted(probe, flat_h1(overrides=TP_BARS), costs=costs).trades
    assert trade.commission == Decimal("2.00")  # 4 × 0.25 lots × 2 sides
    assert trade.net_pnl == trade.gross_pnl - Decimal("2.00")


def test_swap_charged_at_rollover(probe: ProbeStrategy) -> None:
    costs = CostModel(
        spread_pips=Decimal(0),
        commission_per_lot=Decimal(0),
        slippage_pips=Decimal(0),
        swap_long_per_lot=Decimal(-8),
    )
    (trade,) = scripted(probe, flat_h1(30, overrides=ENTRY_BAR), costs=costs).trades
    assert trade.swap == Decimal("-2.00")  # one 21:00 rollover × 0.25 lots
    assert trade.net_pnl == trade.gross_pnl - Decimal("2.00")


# ── determinism & validation ─────────────────────────────────────────────


def test_same_inputs_same_trades_and_metrics(
    candles: list[Candle], baseline: BacktestResult
) -> None:
    strategy = RecordingTrendPullback()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(registry._STRATEGIES, strategy.key, strategy)
        again = run(list(candles), key=strategy.key)
    assert again.trades == baseline.trades
    assert again.metrics == baseline.metrics
    assert again.rejections == baseline.rejections


def test_backtester_rejects_invalid_setups(candles: list[Candle]) -> None:
    with pytest.raises(BacktestError, match="coarser"):
        run([], params=FAST_M15, base_tf=Timeframe.H1)
    with pytest.raises(BacktestError, match="No candles"):
        run([])
    eurjpy = dataclasses.replace(
        SYMBOL, name="EURJPY", quote_currency="JPY", digits=3, point=Decimal("0.001")
    )
    cfg = BacktestConfig(
        "trend_pullback", FAST_M15, eurjpy, SYN_START, SYN_END, Decimal(10000), LOOSE
    )
    with pytest.raises(BacktestError, match="USD"):
        Backtester(cfg, candles, Timeframe.M15)


# ── metrics ──────────────────────────────────────────────────────────────


def stat(pnl: str, day: int, month: int = 1, **kw: Any) -> metrics.TradeStat:
    exit_time = datetime(2025, month, day, 12, tzinfo=UTC)
    return metrics.TradeStat(
        net_pnl=Decimal(pnl),
        entry_time=exit_time - timedelta(hours=2),
        exit_time=exit_time,
        symbol=kw.get("symbol", "EURUSD"),
        side=kw.get("side", "BUY"),
        session=kw.get("session", "LONDON"),
        r_multiple=Decimal(kw["r"]) if "r" in kw else None,
        costs=Decimal(kw.get("costs", "0")),
    )


def test_metrics_on_hand_built_trades() -> None:
    trades = [
        stat("100", 1, r="1"),
        stat("-50", 2, r="-0.5"),
        stat("200", 3, r="2"),
        stat("-50", 4, r="-0.5"),
        stat("-100", 5, r="-1"),
    ]
    m = metrics.compute(trades, Decimal(1000))
    assert m["trades"] == 5 and m["wins"] == 2 and m["losses"] == 3 and m["breakeven"] == 0
    assert m["net_pnl"] == 100.0
    assert m["ending_balance"] == 1100.0
    assert m["return_pct"] == 10.0
    assert m["win_rate"] == 40.0
    assert m["gross_profit"] == 300.0 and m["gross_loss"] == 200.0
    assert m["profit_factor"] == 1.5
    assert m["expectancy"] == 20.0
    assert m["expectancy_r"] == 0.2
    assert m["avg_win"] == 150.0 and m["avg_loss"] == pytest.approx(-66.67)
    assert m["avg_rr"] == 2.25
    assert m["largest_win"] == 200.0 and m["largest_loss"] == -100.0
    assert m["max_consecutive_wins"] == 1
    assert m["max_consecutive_losses"] == 2
    # Equity: 1000 → 1100 → 1050 → 1250 → 1200 → 1100; worst fall 150 from 1250.
    assert m["max_drawdown"] == 150.0
    assert m["max_drawdown_pct"] == 12.0
    assert m["avg_holding_hours"] == 2.0


def test_profit_factor_is_none_without_losses() -> None:
    m = metrics.compute([stat("10", 1), stat("20", 2)], Decimal(1000))
    assert m["profit_factor"] is None
    assert m["avg_rr"] is None and m["avg_loss"] is None
    assert m["win_rate"] == 100.0
    assert m["max_drawdown"] == 0.0 and m["max_drawdown_pct"] == 0.0


def test_metrics_with_no_trades() -> None:
    m = metrics.compute([], Decimal(1000))
    assert m["trades"] == 0
    assert m["win_rate"] is None and m["expectancy"] is None and m["profit_factor"] is None
    assert m["net_pnl"] == 0.0 and m["equity_curve"] == [] and m["monthly"] == []


def test_streaks() -> None:
    pnl = ["10", "10", "10", "-5", "-5", "10", "-5", "-5", "-5", "-5", "10"]
    m = metrics.compute([stat(p, i + 1) for i, p in enumerate(pnl)], Decimal(1000))
    assert m["max_consecutive_wins"] == 3
    assert m["max_consecutive_losses"] == 4


def test_breakeven_trades_break_streaks_and_are_not_losses() -> None:
    m = metrics.compute(
        [stat("-5", 1), stat("0", 2), stat("-5", 3), stat("0", 4), stat("0", 5)], Decimal(1000)
    )
    assert m["breakeven"] == 3 and m["losses"] == 2
    assert m["max_consecutive_losses"] == 1
    assert m["max_consecutive_wins"] == 0


def test_trades_are_ordered_by_exit_time() -> None:
    trades = [stat("-5", 3), stat("10", 1), stat("10", 2)]
    m = metrics.compute(trades, Decimal(1000))
    assert m["max_consecutive_wins"] == 2
    assert [p["equity"] for p in m["equity_curve"]] == [1000.0, 1010.0, 1020.0, 1015.0]


def test_max_drawdown_pct_uses_running_peak() -> None:
    t = datetime(2025, 1, 1, tzinfo=UTC)
    points = [
        (t, Decimal(10000)),
        (t + timedelta(days=1), Decimal(11000)),
        (t + timedelta(days=2), Decimal(9900)),
        (t + timedelta(days=3), Decimal(10500)),
        (t + timedelta(days=4), Decimal(8800)),
        (t + timedelta(days=5), Decimal(12000)),
    ]
    curve, amount, pct = metrics.drawdown_curve(points)
    assert amount == Decimal(2200)
    assert pct == Decimal(20)
    assert [p["dd"] for p in curve] == [0.0, 0.0, -10.0, -4.545, -20.0, 0.0]


def test_monthly_grouping_compounds_returns() -> None:
    trades = [
        stat("100", 5, 1),
        stat("-20", 20, 1),
        stat("-160", 3, 2),
        stat("54", 1, 4),
    ]
    rows = metrics.compute(trades, Decimal(1000))["monthly"]
    assert rows == [
        {"month": "2025-01", "net_pnl": 80.0, "trades": 2, "return_pct": 8.0},
        {"month": "2025-02", "net_pnl": -160.0, "trades": 1, "return_pct": pytest.approx(-14.81)},
        {"month": "2025-04", "net_pnl": 54.0, "trades": 1, "return_pct": 5.87},
    ]


def test_group_stats_by_side_and_session() -> None:
    trades = [
        stat("30", 1, side="BUY", session="LONDON"),
        stat("-10", 2, side="BUY", session="ASIA"),
        stat("-20", 3, side="SELL", session="LONDON"),
    ]
    m = metrics.compute(trades, Decimal(1000))
    by_side = {g["key"]: g for g in m["by_side"]}
    assert by_side["BUY"] == {
        "key": "BUY",
        "trades": 2,
        "wins": 1,
        "win_rate": 50.0,
        "net_pnl": 20.0,
        "profit_factor": 3.0,
    }
    assert by_side["SELL"]["profit_factor"] == 0.0  # no profit over a 20 loss
    assert [g["key"] for g in m["by_session"]] == ["ASIA", "LONDON"]
    assert m["by_strategy"][0]["key"] == "—"


def test_summary_and_downsample() -> None:
    m = metrics.compute([stat("10", 1)], Decimal(1000))
    assert set(metrics.summary(m)) == set(metrics.SUMMARY_KEYS)
    points = list(range(5000))
    picked = metrics.downsample(points, 100)
    assert len(picked) == 100 and picked[0] == 0 and picked[-1] == 4999


def test_engine_metrics_match_its_trades(baseline: BacktestResult) -> None:
    m = baseline.metrics
    net = sum((t.net_pnl for t in baseline.trades), Decimal(0))
    assert m["net_pnl"] == float(net)
    assert m["wins"] == sum(1 for t in baseline.trades if t.net_pnl > 0)
    assert m["total_costs"] == float(sum((t.costs for t in baseline.trades), Decimal(0)))
    assert m["evaluations"] == baseline.evaluations
    assert m["equity_curve"][-1]["equity"] == float(Decimal(10000) + net)
    for t in baseline.trades:
        assert t.net_pnl == t.gross_pnl - t.commission + t.swap


# ── BacktestService through the API ──────────────────────────────────────

API_PARAMS: dict[str, Any] = {
    "ema_fast": 10,
    "ema_slow": 30,
    "slope_lookback": 3,
    "pullback_zone_atr": 1.0,
    "max_extension_atr": 3.0,
    "confirmation": "trend_close",
}
API_RISK = LOOSE.as_json()


@pytest.fixture
def api(client: SignedClient) -> SignedClient:
    return client


@pytest.fixture
def dataset(api: SignedClient, db: Session) -> dict[str, Any]:
    response = api.post(
        "/internal/datasets/synthetic",
        json={"symbol": "EURUSD", "timeframe": "H1", "days": 120, "seed": 5},
    )
    assert response.status_code == 200, response.text
    row = db.get(Dataset, uuid.UUID(response.json()["id"]))
    assert row is not None and row.source is DataSource.SYNTHETIC
    assert row.first_bar is not None and row.last_bar is not None
    return {
        "id": str(row.id),
        "first_bar": row.first_bar.isoformat(),
        "last_bar": row.last_bar.isoformat(),
    }


@pytest.fixture
def empty_dataset(api: SignedClient, db: Session) -> dict[str, Any]:
    """A dataset row without bars — enough for request validation."""
    ds = store.get_or_create_dataset(
        db, symbol="EURUSD", timeframe=Timeframe.H1, source=DataSource.SYNTHETIC
    )
    db.commit()
    return {"id": str(ds.id)}


def window(ds: dict[str, Any], skip_days: int = 25, days: int | None = None) -> dict[str, str]:
    first = datetime.fromisoformat(ds["first_bar"])
    last = datetime.fromisoformat(ds["last_bar"])
    start = Timeframe.D1.floor(first) + timedelta(days=skip_days)
    end = start + timedelta(days=days) if days else Timeframe.D1.floor(last)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _row(b: Backtest) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "kind": b.kind.value,
        "name": b.name,
        "status": b.status.value,
        "error": b.error,
        "progress": b.progress,
        "data_source": b.data_source,
        "data_checksum": b.data_checksum,
        "config": b.config,
        "metrics": b.metrics,
        "report": b.report,
        "warnings": (b.report or {}).get("warnings", []),
        "start": b.start.isoformat(),
        "end": b.end.isoformat(),
    }


def detail(db: Session, backtest_id: str) -> dict[str, Any]:
    db.expire_all()
    row = db.get(Backtest, uuid.UUID(backtest_id))
    assert row is not None
    children = db.scalars(
        select(Backtest).where(Backtest.parent_id == row.id).order_by(Backtest.created_at)
    )
    return _row(row) | {"children": [_row(c) for c in children]}


def trades_of(db: Session, backtest_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(BacktestTrade)
        .where(BacktestTrade.backtest_id == uuid.UUID(backtest_id))
        .order_by(BacktestTrade.entry_time)
    )
    return [
        {
            "signal_time": t.signal_time.isoformat(),
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "entry_price": str(t.entry_price),
            "exit_price": str(t.exit_price),
            "exit_reason": t.exit_reason.value,
            "net_pnl": str(t.net_pnl),
            "volume": str(t.volume),
            "reasons": t.reasons,
        }
        for t in rows
    ]


def _owner(api: SignedClient) -> str:
    with api.app.state.session_factory() as db:  # type: ignore[attr-defined]
        return str(factories.ensure_user(db))


def submit(api: SignedClient, ds: dict[str, Any], **body: Any) -> dict[str, Any]:
    payload = {
        "actor_id": _owner(api),
        "strategy_key": "trend_pullback",
        "initial_capital": "10000",
        "dataset_id": ds["id"],
        "parameters": API_PARAMS,
        "risk": API_RISK,
        **window(ds),
        **body,
    }
    response = api.post("/internal/backtests", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["status"] == "QUEUED"
    ran = api.post(f"/internal/backtests/{created['id']}/run")
    assert ran.status_code == 200, ran.text
    with api.app.state.session_factory() as db:  # type: ignore[attr-defined]
        return detail(db, created["id"])


HISTORICAL = "Historical results do not guarantee future performance."
SYNTHETIC_WARNING = "SYNTHETIC data: these results say nothing about real markets."


def test_single_backtest_via_api(api: SignedClient, dataset: dict[str, Any], db: Session) -> None:
    result = submit(api, dataset, mode="single", name="api single")
    assert result["status"] == "COMPLETED", result["error"]
    assert result["kind"] == "SINGLE" and result["progress"] == 100
    assert result["data_source"] == "synthetic"
    assert result["config"]["synthetic_data"] is True
    assert result["data_checksum"]
    warnings = result["warnings"]
    assert warnings[0] == SYNTHETIC_WARNING
    assert HISTORICAL in warnings
    trades = trades_of(db, result["id"])
    assert len(trades) == result["metrics"]["trades"] > 0
    for t in trades:
        assert t["entry_time"] > t["signal_time"]
        assert t["exit_reason"] in {"STOP_LOSS", "TAKE_PROFIT", "END_OF_TEST"}
        assert t["reasons"]
    if result["metrics"]["trades"] < 30:
        assert any("too few for statistical confidence" in w for w in warnings)
    listed = list_backtests(db)
    assert [str(b.id) for b in listed] == [result["id"]]
    kinds = {n.type for n in db.scalars(select(Notification))}
    assert "backtest.completed" in kinds


def test_single_backtest_is_reproducible(
    api: SignedClient, dataset: dict[str, Any], db: Session
) -> None:
    a = submit(api, dataset, mode="single")
    b = submit(api, dataset, mode="single")
    assert a["data_checksum"] == b["data_checksum"]
    assert a["metrics"] == b["metrics"]
    strip = ("id",)
    trades_a = [{k: v for k, v in t.items() if k not in strip} for t in trades_of(db, a["id"])]
    trades_b = [{k: v for k, v in t.items() if k not in strip} for t in trades_of(db, b["id"])]
    assert trades_a == trades_b


def test_short_backtest_warns_about_too_few_trades(
    api: SignedClient, dataset: dict[str, Any]
) -> None:
    result = submit(api, dataset, mode="single", **window(dataset, skip_days=30, days=4))
    assert result["status"] == "COMPLETED"
    trades = result["metrics"]["trades"]
    assert trades < 30
    assert (
        f"Only {trades} trades — too few for statistical confidence (aim for 30+)."
        in result["warnings"]
    )


def test_split_backtest_via_api(api: SignedClient, dataset: dict[str, Any], db: Session) -> None:
    result = submit(api, dataset, mode="split", split_ratio=0.6)
    assert result["status"] == "COMPLETED", result["error"]
    assert result["kind"] == "SPLIT"
    children = result["children"]
    assert [c["kind"] for c in children] == ["IN_SAMPLE", "OUT_OF_SAMPLE"]
    is_row, oos_row = children
    report = result["report"]
    split_at = datetime.fromisoformat(report["split_at"])
    assert datetime.fromisoformat(is_row["end"]) == split_at
    assert datetime.fromisoformat(oos_row["start"]) == split_at
    assert datetime.fromisoformat(report["split_at"]).hour == 0  # floored to a day
    assert result["metrics"] == oos_row["metrics"]
    assert set(report["in_sample"]) == set(metrics.SUMMARY_KEYS)
    assert "degradation" in report
    assert HISTORICAL in report["warnings"] and SYNTHETIC_WARNING in report["warnings"]
    # Out-of-sample trades are all inside the out-of-sample window.
    oos_trades = trades_of(db, oos_row["id"])
    for t in oos_trades:
        assert datetime.fromisoformat(t["signal_time"]) >= split_at


def test_sensitivity_backtest_via_api(api: SignedClient, dataset: dict[str, Any]) -> None:
    result = submit(api, dataset, mode="sensitivity", grid={"ema_fast": [8, 12]})
    assert result["status"] == "COMPLETED", result["error"]
    assert result["kind"] == "SENSITIVITY"
    assert result["metrics"] is None
    assert [c["name"] for c in result["children"]] == ["ema_fast=8", "ema_fast=12"]
    assert all(c["kind"] == "SENSITIVITY_RUN" for c in result["children"])
    report = result["report"]
    assert [r["params"] for r in report["results"]] == [
        {"ema_fast": 8},
        {"ema_fast": 12},
    ]
    returns = [r["return_pct"] or 0 for r in report["results"]]
    assert report["return_spread"] == pytest.approx(max(returns) - min(returns))
    positive = sum(1 for r in returns if r > 0)
    assert report["profitable_share"] == pytest.approx(positive / 2)
    if positive < 2:
        assert (
            f"Only {positive} of 2 parameter combinations were profitable." in (report["warnings"])
        )


def test_walk_forward_backtest_via_api(api: SignedClient, dataset: dict[str, Any]) -> None:
    result = submit(
        api,
        dataset,
        mode="walk_forward",
        train_months=1,
        test_months=1,
        grid={"ema_fast": [8, 12]},
    )
    assert result["status"] == "COMPLETED", result["error"]
    report = result["report"]
    windows = report["windows"]
    assert report["total_windows"] == len(windows) == len(result["children"]) >= 1
    for w, child in zip(windows, result["children"], strict=True):
        assert child["kind"] == "WALK_FORWARD_WINDOW"
        assert w["test_start"] > w["train_start"]
        # Parameters are chosen on the training window only, then tested after it.
        assert datetime.fromisoformat(w["test_start"]) - datetime.fromisoformat(
            w["train_start"]
        ) == timedelta(days=30)
        assert set(w["chosen"]) == {"ema_fast"}
    oos_total = sum(c["metrics"]["trades"] for c in result["children"])
    assert result["metrics"]["trades"] == oos_total
    assert HISTORICAL in report["warnings"] and SYNTHETIC_WARNING in report["warnings"]


def _error(api: SignedClient, ds_id: str, **body: Any) -> tuple[int, str]:
    payload = {
        "dataset_id": ds_id,
        "parameters": API_PARAMS,
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-02-01T00:00:00Z",
        **body,
    }
    payload.setdefault("strategy_key", "trend_pullback")
    payload.setdefault("actor_id", _owner(api))
    payload.setdefault("initial_capital", "10000")
    response = api.post("/internal/backtests", json=payload)
    return response.status_code, response.text


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        ({"parameters": {**API_PARAMS, "ema_fast": 40}}, 422, "Invalid strategy parameters"),
        ({"parameters": {**API_PARAMS, "nonsense": 1}}, 422, "Invalid strategy parameters"),
        (
            {
                "mode": "sensitivity",
                "grid": {"ema_fast": [5, 6, 7, 8, 9], "atr_period": [5, 6, 7, 8]},
            },
            422,
            "Grid too large (20 runs, max 16)",
        ),
        (
            {
                "mode": "sensitivity",
                "grid": {"ema_fast": [8], "atr_period": [5], "swing_lookback": [5]},
            },
            422,
            "at most two parameters",
        ),
        ({"mode": "sensitivity", "grid": {"bogus": [1]}}, 422, "Unknown parameters in grid"),
        ({"mode": "sensitivity", "grid": {"ema_fast": [40]}}, 422, "Invalid grid value"),
        ({"mode": "sensitivity"}, 422, "needs at least one parameter range"),
        ({"mode": "split", "split_ratio": 0.95}, 422, "split_ratio"),
        ({"end": "2024-12-01T00:00:00Z"}, 422, "End must be after start"),
        ({"end": "2025-01-01T00:00:00Z"}, 422, "End must be after start"),
        ({"risk": {"risk_per_trade_pct": "50"}}, 422, "Invalid risk settings"),
        ({"costs": {"spread_pips": "-1"}}, 422, "Costs cannot be negative"),
        ({"costs": {"commission_per_lot": "abc"}}, 422, "Invalid cost settings"),
        ({"mode": "yolo"}, 422, ""),
        ({"initial_capital": "0"}, 422, ""),
        ({"strategy_key": "martingale"}, 422, "Unknown strategy"),
    ],
)
def test_invalid_backtest_requests(
    api: SignedClient,
    empty_dataset: dict[str, Any],
    body: dict[str, Any],
    status: int,
    message: str,
) -> None:
    code, text = _error(api, empty_dataset["id"], **body)
    assert code == status, text
    assert message in text
    with api.app.state.session_factory() as db:  # type: ignore[attr-defined]
        assert list_backtests(db) == []


def test_unknown_dataset_is_404(api: SignedClient) -> None:
    code, text = _error(api, str(uuid.uuid4()))
    assert code == 404, text
    assert "Dataset not found" in text


def test_range_without_bars_fails_cleanly(
    api: SignedClient, dataset: dict[str, Any], db: Session
) -> None:
    result = submit(
        api, dataset, mode="single", start="2010-01-01T00:00:00Z", end="2010-02-01T00:00:00Z"
    )
    assert result["status"] == "FAILED"
    assert "no bars inside the selected date range" in result["error"]
    assert "backtest.failed" in {n.type for n in db.scalars(select(Notification))}


def test_walk_forward_range_too_short_fails(api: SignedClient, dataset: dict[str, Any]) -> None:
    result = submit(
        api,
        dataset,
        mode="walk_forward",
        train_months=2,
        test_months=2,
        **window(dataset, skip_days=30, days=40),
    )
    assert result["status"] == "FAILED"
    assert "too short" in result["error"]


def test_practice_data_for_one_and_five_minute_candles(api: SignedClient, db: Session) -> None:
    """M1/M5 practice datasets come from the Paper feed (same seed → same prices),
    with a capped period so they stay a sensible size."""
    from fxrobot.market_data.synthetic_feed import SyntheticFeed

    made = api.post(
        "/internal/datasets/synthetic",
        json={"symbol": "EURUSD", "timeframe": "M5", "days": 30, "seed": 42},
    )
    assert made.status_code == 200, made.text
    row = db.get(Dataset, uuid.UUID(made.json()["id"]))
    assert row is not None and row.timeframe is Timeframe.M5 and row.source is DataSource.SYNTHETIC
    assert row.first_bar is not None and row.last_bar is not None
    bars = store.load_candles(db, row.id)
    assert 30 * 288 * 5 / 7 * 0.9 < len(bars) <= 30 * 288
    assert all(b.time.minute % 5 == 0 for b in bars)
    start, end = bars[0].time, bars[-1].time + Timeframe.M5.delta
    assert bars == SyntheticFeed(DEFAULT_SPECS["EURUSD"], 42).bars(Timeframe.M5, start, end)

    one_minute = api.post(
        "/internal/datasets/synthetic",
        json={"symbol": "R_75", "timeframe": "M1", "days": 30, "seed": 1},
    )
    assert one_minute.status_code == 200, one_minute.text
    assert one_minute.json()["bars"] == 30 * 1440  # a 24/7 index: every minute

    too_long = api.post(
        "/internal/datasets/synthetic",
        json={"symbol": "EURUSD", "timeframe": "M1", "days": 90, "seed": 1},
    )
    assert too_long.status_code == 422
    assert "between 30 and 60 for M1" in too_long.text
