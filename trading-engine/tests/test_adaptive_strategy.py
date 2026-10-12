"""Adaptive Trend & Momentum: ADX, the regime classifier, the strategy's decisions,
look-ahead safety, contract support, the new risk rules and its backtests.

Market data here is SYNTHETIC (seeded random walks with a drift and a wave) — it
checks mechanics only and says nothing about real markets.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest

from fxrobot.analytics import metrics
from fxrobot.backtesting.engine import BacktestConfig, Backtester, BacktestError
from fxrobot.backtesting.service import walk_forward_windows
from fxrobot.backtesting.validation import MIN_OOS_TRADES, demo_forward_gate
from fxrobot.domain.contracts import ContractFamily, ContractSpec, StakeQuote
from fxrobot.domain.market import Candle, Quote, Side, Timeframe
from fxrobot.domain.modes import AccountEnvironment, TradingMode
from fxrobot.market_data.resample import resample
from fxrobot.market_data.synthetic import DEFAULT_SPECS
from fxrobot.risk_engine.engine import RiskContext, evaluate, multiplier_amounts
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.strategy_engine import Outcome, get_strategy
from fxrobot.strategy_engine.adaptive_trend_momentum import AdaptiveTrendMomentum
from fxrobot.strategy_engine.base import SignalIntent
from fxrobot.strategy_engine.indicators import adx
from fxrobot.strategy_engine.regime import Regime, RegimeConfig, classify, percentile_rank
from fxrobot.strategy_engine.view import CursorView, StaticView

R10 = DEFAULT_SPECS["R_10"].symbol_info()
START = datetime(2026, 3, 2, tzinfo=UTC)
M5, M15 = Timeframe.M5, Timeframe.M15
STRATEGY = AdaptiveTrendMomentum()
DEFAULTS = STRATEGY.parse_params({})


def gen(
    n: int,
    drift: float,
    seed: int,
    *,
    wave: float = 2.0,
    period: int = 24,
    noise: float = 1.0,
    price: float = 6000.0,
) -> list[Candle]:
    """SYNTHETIC M5 candles: drift + a wave (pullbacks) + noise that slowly shrinks,
    so the latest volatility is not at the top of its own history."""
    rng = random.Random(seed)  # noqa: S311 — deterministic test data, not security
    out: list[Candle] = []
    p = price
    for i in range(n):
        shrink = 1.6 - 0.8 * i / n
        o = p
        c = o + drift + wave * math.sin(2 * math.pi * i / period) + rng.gauss(0, noise) * shrink
        h = max(o, c) + abs(rng.gauss(0, noise)) * 0.5 * shrink
        lo = min(o, c) - abs(rng.gauss(0, noise)) * 0.5 * shrink
        out.append(
            Candle(
                START + timedelta(minutes=5 * i),
                Decimal(f"{o:.3f}"),
                Decimal(f"{h:.3f}"),
                Decimal(f"{lo:.3f}"),
                Decimal(f"{c:.3f}"),
            )
        )
        p = c
    return out


def decisions(
    candles: list[Candle], params: Any = DEFAULTS, first: int = 600
) -> list[tuple[datetime, Any]]:
    view = CursorView(R10, candles, M5, STRATEGY.timeframes(params))
    out = []
    for bar in candles[first:]:
        now = bar.time + M5.delta
        view.set_time(now)
        out.append((now, STRATEGY.evaluate(view, params)))
    return out


def static_view(candles: list[Candle], now: datetime) -> StaticView:
    """What live trading sees at `now`: closed M5 bars, and M15 bars resampled
    from them that had closed by `now`."""
    closed = [c for c in candles if c.time + M5.delta <= now]
    return StaticView(R10, {M5: closed, M15: resample(closed, M15, until=now)})


@pytest.fixture(scope="module")
def uptrend() -> list[Candle]:
    return gen(1400, 0.6, 1)


@pytest.fixture(scope="module")
def downtrend() -> list[Candle]:
    return gen(1400, -0.6, 3)


@pytest.fixture(scope="module")
def sideways() -> list[Candle]:
    return gen(1400, 0.0, 4)


# ── ADX ──────────────────────────────────────────────────────────────────


def reference_adx(
    high: list[float], low: list[float], close: list[float], n: int
) -> tuple[list[float], list[float], list[float]]:
    """Wilder's ADX written out step by step (independent of the vectorised code)."""
    size = len(close)
    nan = float("nan")
    adx_out, pdi, mdi = [nan] * size, [nan] * size, [nan] * size
    trs, pdms, mdms = [], [], []
    for i in range(1, size):
        up, down = high[i] - high[i - 1], low[i - 1] - low[i]
        pdms.append(up if up > down and up > 0 else 0.0)
        mdms.append(down if down > up and down > 0 else 0.0)
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    dx = [nan] * size
    str_, sp, sm = sum(trs[:n]), sum(pdms[:n]), sum(mdms[:n])
    for i in range(n, size):
        if i > n:
            str_ = str_ - str_ / n + trs[i - 1]
            sp = sp - sp / n + pdms[i - 1]
            sm = sm - sm / n + mdms[i - 1]
        pdi[i], mdi[i] = 100 * sp / str_, 100 * sm / str_
        dx[i] = 100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) if pdi[i] + mdi[i] else 0.0
    first = 2 * n - 1
    if size > first:
        adx_out[first] = sum(dx[n : first + 1]) / n
        for i in range(first + 1, size):
            adx_out[i] = (adx_out[i - 1] * (n - 1) + dx[i]) / n
    return adx_out, pdi, mdi


def test_adx_hand_computed_period_2() -> None:
    # Bars 1..3 all move up by 1 with range 2: TR 2, +DM 1, −DM 0 on every bar.
    high = np.array([10.0, 11, 12, 13, 14])
    low = np.array([8.0, 9, 10, 11, 12])
    close = np.array([9.0, 10, 11, 12, 13])
    line, plus, minus = adx(high, low, close, 2)
    # Smoothed TR(2) = 4, +DM(2) = 2 → +DI = 50, −DI = 0, DX = 100 → ADX = 100.
    assert math.isnan(plus[1]) and plus[2] == pytest.approx(50.0) and minus[2] == 0.0
    assert math.isnan(line[2]) and line[3] == pytest.approx(100.0)
    assert line[4] == pytest.approx(100.0)


def test_adx_matches_the_step_by_step_reference() -> None:
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 1, 300))
    high = close + rng.uniform(0, 1, 300)
    low = close - rng.uniform(0, 1, 300)
    line, plus, minus = adx(high, low, close, 14)
    ref = reference_adx(list(high), list(low), list(close), 14)
    for got, want in zip((line, plus, minus), ref, strict=True):
        np.testing.assert_allclose(got, np.array(want), rtol=1e-12, equal_nan=True)
    assert np.isnan(line[:27]).all() and not np.isnan(line[27])
    assert ((line[27:] >= 0) & (line[27:] <= 100)).all()


def test_adx_direction_and_no_lookahead() -> None:
    up = np.arange(100, 160, dtype=float)
    line, plus, minus = adx(up + 0.5, up - 0.5, up, 14)
    assert line[-1] == pytest.approx(100.0) and minus[-1] == 0.0 and plus[-1] > 0
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 1, 200))
    h, lo = c + 0.5, c - 0.5
    full = adx(h, lo, c, 14)[0]
    cut = adx(h[:150], lo[:150], c[:150], 14)[0]
    np.testing.assert_array_equal(full[:150], cut)


# ── regime classifier ────────────────────────────────────────────────────


def test_regime_needs_enough_bars(uptrend: list[Candle]) -> None:
    cfg = RegimeConfig()
    reading = classify(resample(uptrend, M15)[: cfg.required_bars() - 1], cfg)
    assert reading.regime is Regime.UNCERTAIN and "not enough history" in reading.reason


def test_regime_trend_up_down_and_sideways(
    uptrend: list[Candle], downtrend: list[Candle], sideways: list[Candle]
) -> None:
    up = classify(resample(uptrend, M15), RegimeConfig(high_vol_percentile=100))
    down = classify(resample(downtrend, M15), RegimeConfig(high_vol_percentile=100))
    flat = classify(resample(sideways, M15), RegimeConfig(high_vol_percentile=100))
    assert up.regime is Regime.TREND_UP and up.adx is not None and up.adx >= 25
    assert down.regime is Regime.TREND_DOWN and "falling" in down.reason
    assert flat.regime in (Regime.SIDEWAYS, Regime.UNCERTAIN)
    assert up.label().startswith("TREND_UP — ADX")


def test_regime_high_volatility_when_atr_is_at_its_extreme(uptrend: list[Candle]) -> None:
    bars = resample(uptrend, M15)
    last = bars[-1]
    wide = replace(last, high=last.high + 200, low=last.low - 200)  # a volatility spike
    reading = classify([*bars[:-1], wide], RegimeConfig())
    assert reading.regime is Regime.HIGH_VOLATILITY
    assert reading.atr_percentile == pytest.approx(100.0)


def test_regime_rules_are_ordered_and_configurable(uptrend: list[Candle]) -> None:
    bars = resample(uptrend, M15)
    strict = classify(bars, RegimeConfig(trend_adx=95, sideways_adx=1, high_vol_percentile=100))
    assert strict.regime is Regime.UNCERTAIN and "trend not clear" in strict.reason
    with pytest.raises(ValueError, match="sideways_adx"):
        RegimeConfig(trend_adx=20, sideways_adx=30)
    assert percentile_rank(np.array([1.0, 2.0, 3.0, np.nan]), 2.0) == pytest.approx(200 / 3)


def test_regime_is_deterministic(uptrend: list[Candle]) -> None:
    bars = resample(uptrend, M15)
    assert classify(bars) == classify(list(bars))


# ── the strategy's decisions ─────────────────────────────────────────────


def test_buy_signals_in_an_uptrend(uptrend: list[Candle]) -> None:
    found = [e for _, e in decisions(uptrend) if e.signal is not None]
    assert found and all(e.signal.side is Side.BUY for e in found)
    e = found[0]
    sig = e.signal
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.reward_risk == pytest.approx(Decimal(2), abs=Decimal("0.01"))
    names = [c.name for c in e.checks]
    for name in ("Market regime", "Pullback to EMA", "RSI momentum", "Confirmation candle"):
        assert name in names
    assert all(c.passed for c in e.checks)
    regime = next(c for c in e.checks if c.name == "Market regime")
    assert regime.detail.startswith("TREND_UP")


def test_sell_signals_in_a_downtrend(downtrend: list[Candle]) -> None:
    found = [e for _, e in decisions(downtrend) if e.signal is not None]
    assert found and all(e.signal.side is Side.SELL for e in found)
    sig = found[0].signal
    assert sig.take_profit < sig.entry_price < sig.stop_loss


def test_sideways_market_never_trades(sideways: list[Candle]) -> None:
    results = decisions(sideways)
    assert all(e.signal is None for _, e in results)
    regimes = {e.summary.split(" — ")[0] for _, e in results if "regime" in e.summary}
    assert any("SIDEWAYS" in r for r in regimes)
    assert all(e.summary.startswith("No trade") for _, e in results)


def test_weak_trend_is_rejected_with_the_adx_reason(uptrend: list[Candle]) -> None:
    params = STRATEGY.parse_params({"min_adx": 75, "sideways_adx": 5})
    results = decisions(uptrend, params)
    assert all(e.signal is None for _, e in results)
    weak = [e for _, e in results if "trend not clear" in e.summary]
    assert weak
    check = next(c for c in weak[0].checks if c.name == "M15 trend strength")
    assert not check.passed and "min 75" in check.detail


def test_never_trades_on_a_threshold_alone(uptrend: list[Candle]) -> None:
    """Every BUY needs the RSI TURN and the confirmation candle, not just a level."""
    for _, e in decisions(uptrend):
        if e.signal is None:
            continue
        rsi = next(c for c in e.checks if c.name == "RSI momentum")
        assert rsi.passed and "turned up" in rsi.detail


def test_insufficient_candles(uptrend: list[Candle]) -> None:
    view = static_view(uptrend[:300], uptrend[299].time + M5.delta)
    e = STRATEGY.evaluate(view, DEFAULTS)
    assert e.outcome is Outcome.INSUFFICIENT_DATA and e.signal is None
    assert "need" in e.summary and not e.checks[0].passed


def test_stale_trend_data_is_not_traded(uptrend: list[Candle]) -> None:
    now = uptrend[1000].time + M5.delta
    view = static_view(uptrend, now)
    stale = StaticView(R10, {M5: view.candles(M5), M15: list(view.candles(M15))[:-3]})
    e = STRATEGY.evaluate(stale, DEFAULTS)
    assert e.outcome is Outcome.INSUFFICIENT_DATA and e.signal is None
    check = next(c for c in e.checks if c.name == "Data fresh")
    assert not check.passed and "stale" in check.detail


def test_a_forming_trend_bar_is_never_used(uptrend: list[Candle]) -> None:
    """An M15 bar that has not closed at the M5 decision time is ignored, even if a
    view hands it over — with an absurd price it would otherwise change everything."""
    for now, expected in decisions(uptrend)[::25]:
        view = static_view(uptrend, now)
        m15 = list(view.candles(M15))
        forming_open = M15.floor(now)
        if m15 and m15[-1].time == forming_open:
            continue
        crazy = Candle(forming_open, Decimal(1), Decimal(99999), Decimal(1), Decimal(99999))
        leaky = StaticView(R10, {M5: view.candles(M5), M15: [*m15, crazy]})
        assert STRATEGY.evaluate(leaky, DEFAULTS) == expected


# ── look-ahead ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("series", ["uptrend", "downtrend"])
def test_truncated_history_gives_the_identical_decision(
    series: str, request: pytest.FixtureRequest
) -> None:
    """The decision at bar t from data cut at t equals the decision from the full series."""
    candles: list[Candle] = request.getfixturevalue(series)
    full = decisions(candles)
    signal_times = {now for now, e in full if e.signal is not None}
    checked = 0
    for now, expected in full:
        if now not in signal_times and checked % 7:
            checked += 1
            continue
        checked += 1
        cut = [c for c in candles if c.time + M5.delta <= now]
        assert STRATEGY.evaluate(static_view(cut, now), DEFAULTS) == expected, now
    assert signal_times


def test_future_spikes_do_not_change_past_decisions(uptrend: list[Candle]) -> None:
    cutoff = uptrend[1000].time
    spiked = [
        c
        if c.time <= cutoff
        else replace(c, open=c.open * 3, high=c.high * 3, low=c.low / 3, close=c.close / 3)
        for c in uptrend
    ]
    before = [(t, e) for t, e in decisions(uptrend) if t <= cutoff + M5.delta]
    after = [(t, e) for t, e in decisions(spiked) if t <= cutoff + M5.delta]
    assert before == after


# ── parameters, contracts and markets ────────────────────────────────────


def test_default_parameters_match_the_specification() -> None:
    p = DEFAULTS
    assert (p.trend_timeframe, p.entry_timeframe) == (M15, M5)
    assert (p.ema_fast, p.ema_slow, p.rsi_period, p.adx_period, p.atr_period) == (
        20,
        50,
        14,
        14,
        14,
    )
    assert (p.min_adx, p.stop_atr_mult, p.reward_risk) == (25, 1.5, 2.0)
    assert STRATEGY.risk_caps(p) == {
        "risk_per_trade_pct": Decimal("0.5"),
        "max_daily_loss_pct": Decimal("2.0"),
        "max_open_positions": 1,
    }
    assert get_strategy("adaptive_trend_momentum").name == "Adaptive Trend & Momentum"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"ema_fast": 60}, "ema_fast"),
        ({"trend_timeframe": "M5"}, "trend_timeframe"),
        ({"sideways_adx": 30}, "sideways_adx"),
        ({"rsi_level": 75}, "rsi_lower"),
        ({"allow_long": False, "allow_short": False}, "direction"),
        ({"martingale": True}, "Extra inputs"),
    ],
)
def test_invalid_parameters(params: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        STRATEGY.parse_params(params)


def test_rise_fall_and_unchecked_markets_are_refused() -> None:
    problem = STRATEGY.support_problem("R_10", ContractFamily.RISE_FALL)
    assert problem and "Rise/Fall" in problem and "Multiplier" in problem
    assert STRATEGY.support_problem("R_10", ContractFamily.MULTIPLIER) is None
    assert STRATEGY.support_problem("R_25", ContractFamily.SPOT) is None
    other = STRATEGY.support_problem("R_100", ContractFamily.MULTIPLIER)
    assert other and "R_10, R_25" in other
    assert (
        get_strategy("trend_pullback").support_problem("EURUSD", ContractFamily.RISE_FALL) is None
    )


# ── risk engine additions ────────────────────────────────────────────────


def signal(
    side: Side = Side.BUY, entry: str = "6000", stop: str = "5997", tp: str = "6006"
) -> SignalIntent:
    return SignalIntent(
        side=side,
        timeframe=M5,
        bar_time=datetime(2026, 3, 4, 13, 55, tzinfo=UTC),
        entry_price=Decimal(entry),
        stop_loss=Decimal(stop),
        take_profit=Decimal(tp),
        reasons=["test"],
    )


def ctx(**overrides: Any) -> RiskContext:
    now = datetime(2026, 3, 4, 14, 0, 5, tzinfo=UTC)
    quote = Quote("R_10", Decimal("6000"), Decimal("6000.1"), now)
    base: dict[str, Any] = dict(
        now=now,
        mode=TradingMode.DEMO,
        kill_switch_engaged=False,
        platform_halted=False,
        live_trading_locked=True,
        live_authorized=False,
        account_environment=AccountEnvironment.DEMO,
        account_trading_enabled=True,
        broker_connected=True,
        account_currency="USD",
        balance=Decimal(1000),
        equity=Decimal(1000),
        free_margin=Decimal(1000),
        leverage=None,
        symbol=R10,
        quote=quote,
        quote_lookup=lambda name: quote if name == "R_10" else None,
        start_of_day_balance=Decimal(1000),
        start_of_week_balance=Decimal(1000),
        peak_equity=None,
        contract=ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=400),
        stake_quote=StakeQuote(
            Decimal("1.00"),
            Decimal("500.00"),
            stop_loss_min=Decimal("0.10"),
            stop_loss_max=Decimal("1.00"),
            take_profit_min=Decimal("0.10"),
            take_profit_max=Decimal("50.00"),
        ),
    )
    base.update(overrides)
    if base["peak_equity"] is None:
        base["peak_equity"] = base["equity"]
    return RiskContext(**base)


LIMITS = RiskLimits(
    allowed_sessions=("ASIA", "LONDON", "OVERLAP", "NEW_YORK"),
    max_spread_pips=None,
    stake_amount=Decimal("1.00"),
)


def test_multiplier_stop_and_target_become_broker_amounts() -> None:
    decision = evaluate(signal(), ctx(), LIMITS)
    assert decision.approved, decision.rejection_reason
    check = next(c for c in decision.checks if c.rule == "Stop/target amounts")
    # stake 1 × 400 × 3.1 / 6000.1 ≈ 0.21 stop; 5.9 / 6000.1 × 400 ≈ 0.39 target
    assert "stop loss 0.21 USD" in check.detail and "take profit 0.39 USD" in check.detail
    stop, take = multiplier_amounts(signal(), ctx(), Decimal(1))
    assert stop is not None and take is not None and stop <= Decimal(1)


def test_stop_below_the_broker_minimum_is_refused_with_the_reason() -> None:
    tight = signal(stop="5999.5", tp="6001.5")  # 0.6 points: 0.04 USD < 0.10 minimum
    decision = evaluate(tight, ctx(), LIMITS)
    assert not decision.approved
    assert "below the broker's minimum 0.10 USD" in (decision.rejection_reason or "")


def test_stop_beyond_the_stake_is_bounded_by_stop_out() -> None:
    wide = signal(stop="5900", tp="6100")  # a 100-point stop would lose more than the stake
    decision = evaluate(wide, ctx(), LIMITS)
    check = next(c for c in decision.checks if c.rule == "Stop/target amounts")
    assert check.passed and "bounded by the stake" in check.detail


def test_unreported_broker_limits_are_left_to_the_broker() -> None:
    quote = StakeQuote(Decimal("1.00"), Decimal("500.00"))
    decision = evaluate(signal(), ctx(stake_quote=quote), LIMITS)
    assert decision.approved
    check = next(c for c in decision.checks if c.rule == "Stop/target amounts")
    assert "not reported" in check.detail


def test_stake_above_the_risk_budget_is_refused() -> None:
    """0.5 % of a 100 balance is 0.50: a 1.00 stake (the most it can lose) is refused."""
    decision = evaluate(signal(), ctx(balance=Decimal(100), equity=Decimal(100)), LIMITS)
    assert not decision.approved and "per-trade budget" in (decision.rejection_reason or "")


def test_minimum_account_balance() -> None:
    limits = replace(LIMITS, min_account_balance=Decimal(500))
    assert evaluate(signal(), ctx(), limits).approved
    low = ctx(balance=Decimal(400), equity=Decimal(400))
    decision = evaluate(signal(), low, limits)
    assert not decision.approved
    assert decision.rejection_reason == (
        "Minimum balance: balance 400.00 USD is below the minimum 500.00 USD"
    )
    unknown = evaluate(signal(), ctx(balance=None), limits)
    assert not unknown.approved
    with pytest.raises(ValueError, match="min_account_balance"):
        RiskLimits.from_mapping({"min_account_balance": "-1"})


def test_strategy_emergency_stop_rejects_with_the_reason() -> None:
    decision = evaluate(
        signal(), ctx(strategy_disabled="stopped by an administrator: test"), LIMITS
    )
    assert not decision.approved
    assert decision.rejection_reason == "Strategy enabled: stopped by an administrator: test"


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"platform_halted": True}, "Kill switch"),
        ({"kill_switch_engaged": True}, "Kill switch"),
        ({"broker_connected": False}, "Broker connected"),
        (
            {"account_environment": AccountEnvironment.LIVE, "mode": TradingMode.LIVE},
            "Operating mode",
        ),
        (
            {"contract_problem": "Rise/Fall contracts are not offered on R_10."},
            "Contract supported",
        ),
        ({"realized_pnl_today": Decimal(-25)}, "Daily loss limit"),
        ({"stake_quote": None}, "Stake"),
    ],
)
def test_every_gate_rejects_with_a_reason(overrides: dict[str, Any], rule: str) -> None:
    decision = evaluate(signal(), ctx(**overrides), LIMITS.tightened(STRATEGY.risk_caps(DEFAULTS)))
    assert not decision.approved
    assert (decision.rejection_reason or "").startswith(rule)


def test_stale_quote_is_rejected() -> None:
    old = Quote("R_10", Decimal(6000), Decimal("6000.1"), datetime(2026, 3, 4, 13, 0, tzinfo=UTC))
    decision = evaluate(signal(), ctx(quote=old), LIMITS)
    assert (decision.rejection_reason or "").startswith("Market data fresh")


def test_strategy_caps_only_tighten() -> None:
    loose = RiskLimits(risk_per_trade_pct=Decimal(2), max_daily_loss_pct=None, max_open_positions=5)
    tight = loose.tightened(STRATEGY.risk_caps(DEFAULTS))
    assert tight.risk_per_trade_pct == Decimal("0.5")
    assert tight.max_daily_loss_pct == Decimal("2.0")
    assert tight.max_open_positions == 1
    strict = RiskLimits(risk_per_trade_pct=Decimal("0.1"), max_open_positions=1)
    same = strict.tightened(STRATEGY.risk_caps(DEFAULTS))
    assert same.risk_per_trade_pct == Decimal("0.1")  # never loosened
    assert strict.tightened({"stake_amount": 500, "max_drawdown_pct": None}) is strict


def test_one_position_cap_blocks_a_second_trade() -> None:
    from fxrobot.risk_engine.engine import OpenExposure

    open_one = [OpenExposure("R_25", Side.BUY, Decimal(1), Decimal(1))]
    limits = LIMITS.tightened(STRATEGY.risk_caps(DEFAULTS))
    decision = evaluate(signal(), ctx(open_positions=open_one), limits)
    assert (decision.rejection_reason or "").startswith("Open positions")


# ── backtests ────────────────────────────────────────────────────────────


def bt_config(**overrides: Any) -> BacktestConfig:
    values: dict[str, Any] = dict(
        strategy_key="adaptive_trend_momentum",
        params={},
        symbol=R10,
        start=START + timedelta(days=2, hours=12),
        end=START + timedelta(days=6),
        initial_capital=Decimal(1000),
        limits=RiskLimits(
            allowed_sessions=("ASIA", "LONDON", "OVERLAP", "NEW_YORK"),
            max_spread_pips=None,
            min_stop_pips=None,
            max_stop_pips=None,
            cooldown_after_losses=None,
            max_consecutive_losses=None,
            max_trades_per_day=None,
            max_daily_loss_pct=Decimal(50),
            max_weekly_loss_pct=None,
            max_drawdown_pct=None,
            max_data_age_seconds=100_000,
        ),
        contract=ContractSpec(contract_family=ContractFamily.MULTIPLIER, multiplier=400),
        commission_pct=Decimal("0.005"),
        stop_loss_min=Decimal("0.10"),
        take_profit_min=Decimal("0.10"),
    )
    values.update(overrides)
    return BacktestConfig(**values)


@pytest.fixture(scope="module")
def mixed() -> list[Candle]:
    """Up, then sideways, then down: every regime shows up (SYNTHETIC)."""
    up = gen(900, 0.6, 1)
    flat = gen(300, 0.0, 4, price=float(up[-1].close))
    down = gen(600, -0.6, 3, price=float(flat[-1].close))
    out = []
    for i, c in enumerate([*up, *flat, *down]):
        out.append(replace(c, time=START + timedelta(minutes=5 * i)))
    return out


def test_backtest_runs_with_multipliers_and_reports_regimes(mixed: list[Candle]) -> None:
    result = Backtester(bt_config(), mixed, M5).run()
    m = result.metrics
    assert result.trades and m["trades"] == len(result.trades)
    assert all(t.regime in {"TREND_UP", "TREND_DOWN"} for t in result.trades)
    assert {g["key"] for g in m["by_regime"]} <= {"TREND_UP", "TREND_DOWN"}
    assert sum(g["trades"] for g in m["by_regime"]) == m["trades"]
    for g in m["by_regime"] + m["by_symbol"]:
        assert {"expectancy", "avg_rr", "max_drawdown", "longest_losing_streak"} <= set(g)
    assert m["by_symbol"][0]["key"] == "R_10"
    for t in result.trades:
        assert t.contract_type is not None and t.stake == Decimal("1.00")
        assert t.net_pnl >= -t.stake  # a Multiplier never loses more than its stake
        assert t.commission > 0
    assert m["commission_is_estimate"] is True


def test_backtest_is_reproducible(mixed: list[Candle]) -> None:
    a = Backtester(bt_config(), mixed, M5).run()
    b = Backtester(bt_config(), list(mixed), M5).run()
    assert [(t.entry_time, t.net_pnl, t.regime) for t in a.trades] == [
        (t.entry_time, t.net_pnl, t.regime) for t in b.trades
    ]
    assert {k: v for k, v in a.metrics.items()} == {k: v for k, v in b.metrics.items()}


def test_backtest_spot_on_paper_style_data(mixed: list[Candle]) -> None:
    cfg = bt_config(contract=ContractSpec(), commission_pct=Decimal(0))
    result = Backtester(cfg, mixed, M5).run()
    assert result.trades
    for t in result.trades:
        assert t.stop_loss is not None and t.take_profit is not None
        assert t.risk_amount <= Decimal(1000) * Decimal("0.005") + Decimal("0.01")


def test_backtest_refuses_rise_fall_and_other_markets(mixed: list[Candle]) -> None:
    rf = ContractSpec(contract_family=ContractFamily.RISE_FALL, duration=15, duration_unit="m")
    with pytest.raises(BacktestError, match="Rise/Fall"):
        Backtester(bt_config(contract=rf), mixed, M5)
    with pytest.raises(BacktestError, match="R_10, R_25"):
        Backtester(bt_config(symbol=DEFAULT_SPECS["R_100"].symbol_info()), mixed, M5)


def test_backtest_entries_fill_after_the_signal_bar(mixed: list[Candle]) -> None:
    result = Backtester(bt_config(), mixed, M5).run()
    for t in result.trades:
        assert t.entry_time >= t.signal_time + M5.delta


def test_trades_before_a_cut_are_unchanged_by_later_data(mixed: list[Candle]) -> None:
    full = Backtester(bt_config(), mixed, M5).run()
    cut_at = START + timedelta(days=5)
    cut = Backtester(bt_config(end=cut_at), [c for c in mixed if c.time < cut_at], M5).run()
    early = [
        (t.entry_time, t.side, t.regime)
        for t in full.trades
        if t.exit_time and t.exit_time < cut_at
    ]
    assert early == [
        (t.entry_time, t.side, t.regime)
        for t in cut.trades
        if t.exit_time
        and t.exit_time < cut_at
        and t.exit_reason is not None
        and t.exit_reason.value != "END_OF_TEST"
    ]


# ── validation gate ──────────────────────────────────────────────────────


def test_validation_gate_needs_real_data_sample_expectancy_and_stability() -> None:
    good_folds = [{"trades": 40, "expectancy": 0.2}] * 3 + [{"trades": 30, "expectancy": -0.1}]
    oos = {"trades": MIN_OOS_TRADES, "expectancy": 0.05, "expectancy_r_tstat": 2.4}
    passed = demo_forward_gate(oos, good_folds, synthetic=False)
    assert passed["qualifies_for_demo_forward_testing"] is True and passed["reasons"] == []
    assert "nothing is enabled automatically" in passed["note"]

    synthetic = demo_forward_gate(oos, good_folds, synthetic=True)
    assert not synthetic["qualifies_for_demo_forward_testing"]
    noise = demo_forward_gate({**oos, "expectancy_r_tstat": 0.5}, good_folds, synthetic=False)
    assert not noise["qualifies_for_demo_forward_testing"]
    assert noise["reasons"] == ["t-statistic of the mean R is 0.50 (need at least 2)"]
    few = demo_forward_gate(
        {"trades": 99, "expectancy": 1.0, "expectancy_r_tstat": 3.0}, good_folds, synthetic=False
    )
    assert "99 out-of-sample trades" in few["reasons"][0]
    losing = demo_forward_gate(
        {"trades": 300, "expectancy": -0.01, "expectancy_r_tstat": -0.4},
        good_folds,
        synthetic=False,
    )
    assert not losing["qualifies_for_demo_forward_testing"]
    unstable_folds = [{"trades": 40, "expectancy": 0.5}] + [{"trades": 40, "expectancy": -0.1}] * 3
    unstable = demo_forward_gate(oos, unstable_folds, synthetic=False)
    assert "1 of 4 folds" in unstable["reasons"][0]
    split_only = demo_forward_gate(oos, None, synthetic=False)
    assert "walk-forward" in split_only["reasons"][0]


def test_walk_forward_windows_never_overlap() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    windows = walk_forward_windows(
        start, start + timedelta(days=300), timedelta(days=90), timedelta(days=30)
    )
    assert len(windows) == 7
    for (_, t1, t2), (_, n1, _) in itertools.pairwise(windows):
        assert t2 <= n1 and t1 < t2


def test_group_stats_by_regime_metrics() -> None:
    t0 = datetime(2026, 1, 5, tzinfo=UTC)

    def st(pnl: str, h: int, regime: str) -> metrics.TradeStat:
        return metrics.TradeStat(
            Decimal(pnl),
            t0 + timedelta(hours=h),
            t0 + timedelta(hours=h + 1),
            "R_10",
            "BUY",
            "ASIA",
            Decimal(pnl),
            Decimal(0),
            regime=regime,
        )

    m = metrics.compute(
        [
            st("2", 1, "TREND_UP"),
            st("-1", 2, "TREND_UP"),
            st("-1", 3, "TREND_UP"),
            st("-1", 4, "TREND_DOWN"),
        ],
        Decimal(100),
    )
    up = next(g for g in m["by_regime"] if g["key"] == "TREND_UP")
    assert up["trades"] == 3 and up["expectancy"] == pytest.approx(0.0)
    assert up["max_drawdown"] == 2.0 and up["longest_losing_streak"] == 2 and up["avg_rr"] == 2.0
    # mean R −0.25 over [2, −1, −1, −1]: sd 1.5, se 0.75 → t = −0.33
    assert m["expectancy_r_tstat"] == pytest.approx(-0.33)
    assert metrics.compute([], Decimal(100))["by_regime"] == []


def test_cursor_view_prefix_never_reaches_unclosed_bars(uptrend: list[Candle]) -> None:
    view = CursorView(R10, uptrend, M5, (M5, M15))
    now = uptrend[100].time + M5.delta
    view.set_time(now)
    bars = view.candles(M5)
    assert len(bars) == 101 and bars[-1] == uptrend[100] and bars[0] == uptrend[0]
    assert bars[-3:] == uptrend[98:101] and list(bars) == uptrend[:101]
    assert bars == uptrend[:101]
    with pytest.raises(IndexError):
        bars[101]
    assert all(c.time + M15.delta <= now for c in view.candles(M15))
