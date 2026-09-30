"""Strategy engine: indicators, parameter validation, Trend Pullback V1 decisions
on hand-crafted candle series, and the market views that guard against look-ahead."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from fxrobot.domain.market import Candle, Side, Timeframe
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries
from fxrobot.strategy_engine import Outcome, get_strategy, list_strategies
from fxrobot.strategy_engine.base import Check, Evaluation
from fxrobot.strategy_engine.indicators import atr, ema, swing_points
from fxrobot.strategy_engine.trend_pullback import TrendPullbackParams, TrendPullbackV1
from fxrobot.strategy_engine.view import CursorView, StaticView

SYMBOL = DEFAULT_SPECS["EURUSD"].symbol_info()
T0 = datetime(2025, 3, 3, tzinfo=UTC)  # Monday 00:00 UTC
STRATEGY = TrendPullbackV1()

# Small windows: htf_window = 10*2 + 2 + 5 = 27, ltf_window = max(15, 25, 14) = 25.
SMALL: dict[str, Any] = {
    "ema_fast": 5,
    "ema_slow": 10,
    "slope_lookback": 2,
    "atr_period": 5,
    "pullback_lookback": 4,
    "swing_lookback": 5,
}


def params(**overrides: Any) -> TrendPullbackParams:
    return TrendPullbackParams.model_validate({**SMALL, **overrides})


def bars_from_path(
    path: Sequence[float], tf: Timeframe, wick: float = 0.0003, start: datetime = T0
) -> list[Candle]:
    """Bar i opens at path[i] and closes at path[i+1], with symmetric wicks."""
    out = []
    for i in range(len(path) - 1):
        o, c = path[i], path[i + 1]
        out.append(
            Candle(
                start + i * tf.delta,
                Decimal(f"{o:.5f}"),
                Decimal(f"{max(o, c) + wick:.5f}"),
                Decimal(f"{min(o, c) - wick:.5f}"),
                Decimal(f"{c:.5f}"),
            )
        )
    return out


def mirror(path: Sequence[float], axis: float = 2.2) -> list[float]:
    return [axis - p for p in path]


def uptrend_htf() -> list[float]:
    return [1.1 + 0.002 * i for i in range(40)]


def pullback_ltf() -> list[float]:
    up = [1.1 + 0.001 * i for i in range(26)]
    last = up[-1]
    # Three bars of pullback, then a bullish bar closing above the previous high.
    return [*up, last - 0.0008, last - 0.0016, last - 0.0024, last - 0.0005]


def view_for(ltf_path: Sequence[float], htf_path: Sequence[float]) -> StaticView:
    return StaticView(
        SYMBOL,
        {
            Timeframe.H1: bars_from_path(ltf_path, Timeframe.H1),
            Timeframe.H4: bars_from_path(htf_path, Timeframe.H4),
        },
    )


def arrays(candles: Sequence[Candle]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.array([float(c.high) for c in candles]),
        np.array([float(c.low) for c in candles]),
        np.array([float(c.close) for c in candles]),
    )


def assert_explained(evaluation: Evaluation) -> None:
    assert evaluation.summary
    for check in evaluation.checks:
        assert isinstance(check, Check)
        assert check.name.strip(), check
        assert check.detail.strip(), check
        assert isinstance(check.passed, bool)
    assert all(set(c) == {"name", "passed", "detail"} for c in evaluation.checks_json())


# ── indicators ───────────────────────────────────────────────────────────


def test_ema_matches_hand_computed_values() -> None:
    out = ema(np.array([2.0, 4.0, 6.0, 8.0, 4.0, 2.0]), 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    # Seed = SMA(2,4,6) = 4; alpha = 2/(3+1) = 0.5.
    assert out[2:].tolist() == pytest.approx([4.0, 6.0, 5.0, 3.5])


def test_ema_with_non_trivial_alpha() -> None:
    values = np.array([10.0, 11.0, 12.0, 13.0, 9.0])
    out = ema(values, 4)  # alpha = 0.4, seed = 11.5
    assert out[3] == pytest.approx(11.5)
    assert out[4] == pytest.approx(0.4 * 9.0 + 0.6 * 11.5)


@pytest.mark.parametrize("period", [0, -1, 7])
def test_ema_without_enough_data_is_all_nan(period: int) -> None:
    assert np.isnan(ema(np.arange(5, dtype=float), period)).all()


def test_atr_matches_wilder_by_hand() -> None:
    high = np.array([10.0, 12.0, 13.0, 12.5, 14.0])
    low = np.array([9.0, 10.0, 11.0, 10.0, 12.0])
    close = np.array([9.5, 11.5, 12.0, 11.0, 13.5])
    out = atr(high, low, close, 2)
    # True ranges from bar 1: max(h-l, |h-pc|, |l-pc|)
    # bar1: max(2, 2.5, 0.5)=2.5 ; bar2: max(2, 1.5, 0.5)=2 ; bar3: max(2.5, .5, 2)=2.5
    # bar4: max(2, 3, 1)=3
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx((2.5 + 2.0) / 2)
    assert out[3] == pytest.approx((2.25 * 1 + 2.5) / 2)
    assert out[4] == pytest.approx((2.375 * 1 + 3.0) / 2)


def test_atr_short_series_is_nan() -> None:
    assert np.isnan(atr(np.ones(3), np.ones(3), np.ones(3), 3)).all()


@pytest.mark.parametrize("fn", ["ema", "atr"])
def test_indicators_have_no_look_ahead(fn: str) -> None:
    rng = np.random.default_rng(5)
    close = 1.1 + np.cumsum(rng.normal(0, 0.001, 200))
    high, low = close + 0.0005, close - 0.0005

    def compute(n: int) -> np.ndarray:
        if fn == "ema":
            return ema(close[:n], 14)
        return atr(high[:n], low[:n], close[:n], 14)

    full = compute(200)
    for n in (20, 57, 120, 199):
        np.testing.assert_array_equal(compute(n), full[:n])


def test_swing_points_by_hand() -> None:
    high = np.array([1.0, 2.0, 5.0, 2.0, 1.0, 3.0, 9.0])
    low = np.array([0.5, 1.0, 4.0, 0.2, 0.8, 2.0, 8.0])
    highs, lows = swing_points(high, low, 2, 2)
    assert highs == [2]  # index 6 (9.0) is too recent to be confirmed
    assert lows == [3]


def test_swing_points_ignore_equal_extremes() -> None:
    high = np.array([1.0, 2.0, 5.0, 5.0, 2.0, 1.0, 0.5])
    low = high - 0.5
    highs, _ = swing_points(high, low, 2, 2)
    assert 2 not in highs and 3 not in highs


@pytest.mark.parametrize("right", [1, 2, 3, 5])
def test_swing_points_never_include_last_right_bars(right: int) -> None:
    rng = np.random.default_rng(right)
    for _ in range(20):
        close = np.cumsum(rng.normal(0, 1, 60))
        high, low = close + rng.random(60), close - rng.random(60)
        highs, lows = swing_points(high, low, 2, right)
        assert all(i < 60 - right for i in highs + lows)
        # And a confirmed swing stays a swing when more bars arrive.
        more_h, more_l = swing_points(
            np.concatenate([high, high[:10] + 100]), np.concatenate([low, low[:10] - 100]), 2, right
        )
        assert set(highs) <= set(more_h) and set(lows) <= set(more_l)


# ── parameters ───────────────────────────────────────────────────────────


def test_default_params_are_valid_and_complete() -> None:
    defaults = STRATEGY.default_params()
    assert defaults["ema_fast"] == 50 and defaults["ema_slow"] == 200
    assert defaults["higher_timeframe"] == "H4" and defaults["entry_timeframe"] == "H1"
    assert STRATEGY.parse_params(defaults) == TrendPullbackParams()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"ema_fast": 30, "ema_slow": 30}, "ema_fast must be smaller"),
        ({"ema_fast": 40, "ema_slow": 30}, "ema_fast must be smaller"),
        ({"higher_timeframe": "H1", "entry_timeframe": "H1"}, "higher_timeframe must be above"),
        ({"higher_timeframe": "M15", "entry_timeframe": "H1"}, "higher_timeframe must be above"),
        ({"allow_long": False, "allow_short": False}, "at least one direction"),
        ({"surprise": 1}, "Extra inputs are not permitted"),
        ({"ema_fast": 4}, "greater than or equal to 5"),
        ({"confirmation": "vibes"}, "confirmation"),
        ({"stop_mode": "none"}, "stop_mode"),
    ],
)
def test_invalid_params_are_rejected(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        STRATEGY.parse_params({**SMALL, **override})


def test_timeframes_and_required_bars() -> None:
    p = params(entry_timeframe="M15", higher_timeframe="H1")
    assert STRATEGY.timeframes(p) == (Timeframe.M15, Timeframe.H1)
    assert STRATEGY.required_bars(p) == {Timeframe.M15: 25, Timeframe.H1: 27}
    default = TrendPullbackParams()
    assert default.htf_window() == 200 * 2 + 10 + 5
    assert default.ltf_window() == 150


def test_registry() -> None:
    assert get_strategy("trend_pullback").key == "trend_pullback"
    assert [s.key for s in list_strategies()] == ["trend_pullback"]
    with pytest.raises(KeyError, match="Unknown strategy"):
        get_strategy("martingale")


# ── evaluation on crafted series ─────────────────────────────────────────


def test_uptrend_pullback_confirmation_gives_buy_with_swing_stop() -> None:
    view = view_for(pullback_ltf(), uptrend_htf())
    p = params()
    ev = STRATEGY.evaluate(view, p)
    assert ev.outcome is Outcome.SIGNAL, ev.summary
    assert ev.summary == "BUY signal: H4 trend, pullback to EMA5, confirmed."
    assert all(c.passed for c in ev.checks)
    assert_explained(ev)
    sig = ev.signal
    assert sig is not None
    assert sig.side is Side.BUY and sig.timeframe is Timeframe.H1
    ltf = list(view.candles(Timeframe.H1))[-p.ltf_window() :]
    assert sig.bar_time == ltf[-1].time == ev.bar_time
    assert sig.entry_price == ltf[-1].close
    high, low, close = arrays(ltf)
    cur_atr = atr(high, low, close, p.atr_period)[-1]
    swing_low = low[-p.swing_lookback :].min()
    expected_stop = swing_low - p.stop_buffer_atr * cur_atr
    assert float(sig.stop_loss) == pytest.approx(expected_stop, abs=1e-5)
    assert float(sig.stop_loss) < swing_low  # beyond the swing
    expected_tp = float(sig.entry_price) + p.reward_risk * (float(sig.entry_price) - expected_stop)
    assert float(sig.take_profit or 0) == pytest.approx(expected_tp, abs=1e-5)
    assert sig.reward_risk == pytest.approx(Decimal(2), abs=Decimal("0.01"))
    # Prices are quantized to the symbol's digits.
    assert sig.stop_loss.as_tuple().exponent == -SYMBOL.digits
    assert sig.reasons == [c.detail for c in ev.checks]


def test_mirrored_downtrend_gives_sell_with_stop_above_swing() -> None:
    view = view_for(mirror(pullback_ltf()), mirror(uptrend_htf()))
    p = params()
    ev = STRATEGY.evaluate(view, p)
    assert ev.outcome is Outcome.SIGNAL, ev.summary
    assert_explained(ev)
    sig = ev.signal
    assert sig is not None and sig.side is Side.SELL
    ltf = list(view.candles(Timeframe.H1))[-p.ltf_window() :]
    high, low, close = arrays(ltf)
    cur_atr = atr(high, low, close, p.atr_period)[-1]
    swing_high = high[-p.swing_lookback :].max()
    assert float(sig.stop_loss) == pytest.approx(swing_high + 0.2 * cur_atr, abs=1e-5)
    assert sig.stop_loss > sig.entry_price > (sig.take_profit or Decimal(0))
    assert sig.reward_risk == pytest.approx(Decimal(2), abs=Decimal("0.01"))
    assert [c.name for c in ev.checks][:3] == [
        "SELL: HTF close vs EMA10",
        "SELL: HTF EMA5 vs EMA10",
        "SELL: HTF EMA10 slope",
    ]


def test_atr_stop_and_atr_target_modes() -> None:
    view = view_for(pullback_ltf(), uptrend_htf())
    p = params(stop_mode="atr", stop_atr_mult=2.0, take_profit_mode="atr", tp_atr_mult=3.0)
    ev = STRATEGY.evaluate(view, p)
    assert ev.signal is not None
    ltf = list(view.candles(Timeframe.H1))[-p.ltf_window() :]
    cur_atr = atr(*arrays(ltf), p.atr_period)[-1]
    entry = float(ev.signal.entry_price)
    assert float(ev.signal.stop_loss) == pytest.approx(entry - 2.0 * cur_atr, abs=1e-5)
    assert float(ev.signal.take_profit or 0) == pytest.approx(entry + 3.0 * cur_atr, abs=1e-5)


def test_flat_market_is_no_setup() -> None:
    flat = [1.1 + (0.0002 if i % 2 else 0.0) for i in range(60)]
    ev = STRATEGY.evaluate(view_for(flat, flat), params())
    assert ev.outcome is Outcome.NO_SETUP
    assert ev.summary == "No clear higher-timeframe trend."
    assert ev.signal is None
    # Both directions were examined and explained.
    names = [c.name for c in ev.checks]
    assert any(n.startswith("BUY:") for n in names) and any(n.startswith("SELL:") for n in names)
    assert_explained(ev)


def test_trend_without_pullback_is_no_setup() -> None:
    steep = [1.1 + 0.003 * i for i in range(40)]
    ev = STRATEGY.evaluate(view_for(steep, uptrend_htf()), params())
    assert ev.outcome is Outcome.NO_SETUP
    assert ev.summary == "BUY trend, but pullback to ema not met."
    assert next(c for c in ev.checks if c.name == "Pullback to EMA").passed is False
    assert_explained(ev)


def test_missing_confirmation_is_no_setup() -> None:
    path = [*pullback_ltf()[:-1], pullback_ltf()[-2] - 0.0003]  # last bar keeps falling
    ev = STRATEGY.evaluate(view_for(path, uptrend_htf()), params())
    assert ev.outcome is Outcome.NO_SETUP
    assert next(c for c in ev.checks if c.name == "Confirmation").passed is False


def test_disallowed_direction_is_no_setup() -> None:
    ev = STRATEGY.evaluate(view_for(pullback_ltf(), uptrend_htf()), params(allow_long=False))
    assert ev.outcome is Outcome.NO_SETUP
    assert ev.signal is None
    assert all(c.name.startswith("SELL:") for c in ev.checks)


@pytest.mark.parametrize(("ltf_bars", "htf_bars"), [(24, 39), (40, 26), (0, 0)])
def test_short_history_is_insufficient_data(ltf_bars: int, htf_bars: int) -> None:
    ltf = bars_from_path(pullback_ltf(), Timeframe.H1)[-ltf_bars:] if ltf_bars else []
    htf = bars_from_path(uptrend_htf(), Timeframe.H4)[-htf_bars:] if htf_bars else []
    ev = STRATEGY.evaluate(StaticView(SYMBOL, {Timeframe.H1: ltf, Timeframe.H4: htf}), params())
    assert ev.outcome is Outcome.INSUFFICIENT_DATA
    assert ev.signal is None
    assert ev.summary == (
        f"Need 25 H1 and 27 H4 closed bars (have {min(ltf_bars, 25)} / {min(htf_bars, 27)})."
    )


def test_evaluation_is_deterministic() -> None:
    view = view_for(pullback_ltf(), uptrend_htf())
    first, second = STRATEGY.evaluate(view, params()), STRATEGY.evaluate(view, params())
    assert first == second
    assert first.checks_json() == second.checks_json()


def test_only_the_recent_window_matters() -> None:
    """Older history beyond the lookback windows cannot change the decision."""
    base = view_for(pullback_ltf(), uptrend_htf())
    longer_ltf = [1.0 + 0.0001 * i for i in range(50)] + pullback_ltf()
    longer = view_for(longer_ltf, [0.9, 1.3, *uptrend_htf()])
    a, b = STRATEGY.evaluate(base, params()), STRATEGY.evaluate(longer, params())
    assert a.outcome is b.outcome is Outcome.SIGNAL
    assert a.signal is not None and b.signal is not None
    assert (a.signal.entry_price, a.signal.stop_loss, a.signal.take_profit) == (
        b.signal.entry_price,
        b.signal.stop_loss,
        b.signal.take_profit,
    )


def test_check_coerces_numpy_bools() -> None:
    check = Check("x", np.bool_(True), "d")  # type: ignore[arg-type]
    assert check.passed is True
    assert check.as_dict() == {"name": "x", "passed": True, "detail": "d"}


def test_signal_intent_risk_properties() -> None:
    ev = STRATEGY.evaluate(view_for(pullback_ltf(), uptrend_htf()), params())
    sig = ev.signal
    assert sig is not None
    assert sig.risk_distance == sig.entry_price - sig.stop_loss
    assert sig.reward_risk == abs((sig.take_profit or Decimal(0)) - sig.entry_price) / (
        sig.risk_distance
    )


# ── views ────────────────────────────────────────────────────────────────


def m15_series(days: int = 3, start: datetime = T0) -> list[Candle]:
    series = SyntheticSeries(DEFAULT_SPECS["EURUSD"], 9, start, Timeframe.M15)
    return series.bars(start, start + timedelta(days=days))


def test_static_view_returns_given_candles_only() -> None:
    candles = bars_from_path(pullback_ltf(), Timeframe.H1)
    view = StaticView(SYMBOL, {Timeframe.H1: candles})
    assert list(view.candles(Timeframe.H1)) == candles
    assert list(view.candles(Timeframe.H4)) == []
    assert view.symbol is SYMBOL


def test_cursor_view_hides_everything_before_time_is_set() -> None:
    view = CursorView(SYMBOL, m15_series(), Timeframe.M15, [Timeframe.H1])
    assert list(view.candles(Timeframe.M15)) == []
    assert list(view.candles(Timeframe.H1)) == []


def test_cursor_view_exact_visibility_at_a_known_time() -> None:
    base = m15_series()
    view = CursorView(SYMBOL, base, Timeframe.M15, [Timeframe.H1, Timeframe.H4])
    now = T0 + timedelta(hours=10, minutes=45)
    view.set_time(now)
    m15, h1, h4 = (list(view.candles(tf)) for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4))
    assert m15[-1].time == T0 + timedelta(hours=10, minutes=30)  # closes at 10:45
    assert h1[-1].time == T0 + timedelta(hours=9)  # 10:00 bar still forming
    assert h4[-1].time == T0 + timedelta(hours=4)  # 08:00 bar still forming
    # Resampled H1 bar = merge of its four M15 bars.
    parts = [c for c in base if T0 + timedelta(hours=9) <= c.time < T0 + timedelta(hours=10)]
    assert len(parts) == 4
    assert h1[-1].open == parts[0].open and h1[-1].close == parts[-1].close
    assert h1[-1].high == max(c.high for c in parts)
    assert h1[-1].low == min(c.low for c in parts)
    # A timeframe the strategy did not declare is simply empty.
    assert list(view.candles(Timeframe.D1)) == []


def test_cursor_view_bar_becomes_visible_exactly_when_it_closes() -> None:
    view = CursorView(SYMBOL, m15_series(), Timeframe.M15, [Timeframe.H4])
    h4_open = T0 + timedelta(hours=8)
    view.set_time(h4_open + Timeframe.H4.delta - timedelta(seconds=1))
    assert list(view.candles(Timeframe.H4))[-1].time == T0 + timedelta(hours=4)
    view.set_time(h4_open + Timeframe.H4.delta)
    assert list(view.candles(Timeframe.H4))[-1].time == h4_open


def test_cursor_view_never_exposes_unclosed_bars_at_any_time() -> None:
    base = m15_series(days=4)
    tfs = [Timeframe.H1, Timeframe.H4, Timeframe.D1]
    view = CursorView(SYMBOL, base, Timeframe.M15, tfs)
    for minutes in range(0, 4 * 24 * 60 + 60, 35):  # deliberately off-grid times too
        now = T0 + timedelta(minutes=minutes)
        view.set_time(now)
        for tf in [Timeframe.M15, *tfs]:
            visible = list(view.candles(tf))
            assert all(c.time + tf.delta <= now for c in visible), (tf, now)
            # ...and nothing that HAS closed is hidden.
            all_bars = view._series[tf]
            hidden_closed = [c for c in all_bars[len(visible) :] if c.time + tf.delta <= now]
            assert hidden_closed == []


def test_cursor_view_drops_incomplete_trailing_higher_timeframe_bar() -> None:
    base = [c for c in m15_series() if c.time < T0 + timedelta(hours=6)]  # ends mid-H4 bar
    view = CursorView(SYMBOL, base, Timeframe.M15, [Timeframe.H4])
    view.set_time(T0 + timedelta(days=30))
    assert [c.time for c in view.candles(Timeframe.H4)] == [T0]


def test_higher_timeframe_bars_do_not_depend_on_future_base_bars() -> None:
    base = m15_series(days=3)
    cut = T0 + timedelta(days=1, hours=13)
    spiked = [
        c
        if c.time < cut
        else Candle(c.time, c.open * 2, c.high * 3, c.low / 3, c.close * 2, c.tick_volume)
        for c in base
    ]
    views = [
        CursorView(SYMBOL, b, Timeframe.M15, [Timeframe.H1, Timeframe.H4]) for b in (base, spiked)
    ]
    for v in views:
        v.set_time(cut)
    for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
        assert list(views[0].candles(tf)) == list(views[1].candles(tf))


def test_strategy_through_cursor_view_matches_static_view_of_closed_bars() -> None:
    base = m15_series(days=10)
    p = params(entry_timeframe="H1", higher_timeframe="H4")
    view = CursorView(SYMBOL, base, Timeframe.M15, STRATEGY.timeframes(p))
    for hours in (60, 101, 150, 200):
        now = T0 + timedelta(hours=hours)
        view.set_time(now)
        closed = {
            tf: [c for c in view._series[tf] if c.time + tf.delta <= now]
            for tf in (Timeframe.H1, Timeframe.H4)
        }
        assert STRATEGY.evaluate(view, p) == STRATEGY.evaluate(StaticView(SYMBOL, closed), p)
