"""Trend Pullback V1 — multi-timeframe trend-following research strategy.

Idea (every threshold below is a parameter):
1. Higher timeframe (default H4) defines the trend: price vs EMA(slow),
   EMA(fast) vs EMA(slow), slope of EMA(slow), optional swing structure.
2. Entry timeframe (default H1) must have PULLED BACK towards EMA(fast)
   recently — without breaking too deep (trend damage).
3. Don't chase: the signal bar may not be over-extended from EMA(fast).
4. A confirmation bar must show the trend resuming.
5. Stop = beyond the recent swing (or N×ATR). Target = R-multiple or N×ATR.

This is a research starting point. It is not claimed to be profitable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fxrobot.domain.market import Side, Timeframe
from fxrobot.strategy_engine.base import (
    Check,
    Evaluation,
    MarketView,
    Outcome,
    SignalIntent,
    Strategy,
)
from fxrobot.strategy_engine.indicators import atr, ema, swing_points

Confirmation = Literal["close_beyond_prev_extreme", "trend_close", "engulfing"]


class TrendPullbackParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    higher_timeframe: Timeframe = Field(
        Timeframe.H4, description="Timeframe that defines the trend."
    )
    entry_timeframe: Timeframe = Field(Timeframe.H1, description="Timeframe used for entries.")
    ema_fast: int = Field(50, ge=5, le=400, description="Fast EMA period.")
    ema_slow: int = Field(200, ge=10, le=800, description="Slow EMA period.")
    require_fast_above_slow: bool = Field(
        True, description="HTF fast EMA must be on the trend side of the slow EMA."
    )
    require_slope: bool = Field(True, description="HTF slow EMA must slope in the trend direction.")
    slope_lookback: int = Field(
        10, ge=1, le=100, description="Bars used to measure the slow EMA slope."
    )
    use_structure: bool = Field(
        False, description="Also require higher highs/lows (or lower) on the HTF."
    )
    atr_period: int = Field(14, ge=2, le=100)
    pullback_lookback: int = Field(
        6, ge=1, le=50, description="Entry bars in which a pullback must have happened."
    )
    pullback_zone_atr: float = Field(
        0.5, ge=0, le=5, description="How close (in ATR) price must come to the fast EMA."
    )
    max_pullback_atr: float = Field(
        2.5, ge=0.1, le=10, description="Deepest allowed pullback beyond the fast EMA (ATR)."
    )
    max_extension_atr: float = Field(
        1.5,
        ge=0.1,
        le=10,
        description="Don't chase: max distance of the close from the fast EMA (ATR).",
    )
    confirmation: Confirmation = Field(
        "close_beyond_prev_extreme", description="Bar pattern that confirms the trend resumed."
    )
    stop_mode: Literal["swing", "atr"] = Field(
        "swing", description="Stop beyond the recent swing, or a fixed ATR multiple."
    )
    swing_lookback: int = Field(
        10, ge=2, le=100, description="Bars searched for the protective swing."
    )
    stop_buffer_atr: float = Field(
        0.2, ge=0, le=5, description="Extra distance beyond the swing (ATR)."
    )
    stop_atr_mult: float = Field(
        1.5, ge=0.2, le=10, description="Stop distance when stop_mode = atr."
    )
    take_profit_mode: Literal["rr", "atr"] = Field(
        "rr", description="Target as an R-multiple or ATR multiple."
    )
    reward_risk: float = Field(
        2.0, ge=0.5, le=10, description="Target = entry ± reward_risk × stop distance."
    )
    tp_atr_mult: float = Field(3.0, ge=0.5, le=20)
    allow_long: bool = True
    allow_short: bool = True

    @model_validator(mode="after")
    def _check(self) -> TrendPullbackParams:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        if self.higher_timeframe.seconds <= self.entry_timeframe.seconds:
            raise ValueError("higher_timeframe must be above entry_timeframe")
        if not (self.allow_long or self.allow_short):
            raise ValueError("allow at least one direction")
        return self

    def htf_window(self) -> int:
        return self.ema_slow * 2 + self.slope_lookback + 5

    def ltf_window(self) -> int:
        return max(
            self.ema_fast * 3, self.atr_period * 5, self.swing_lookback + self.pullback_lookback + 5
        )


class TrendPullbackV1(Strategy):
    key: ClassVar[str] = "trend_pullback"
    name: ClassVar[str] = "Trend Pullback V1"
    code_version: ClassVar[str] = "1.0.0"
    description: ClassVar[str] = (
        "Trades in the direction of the higher-timeframe trend after a pullback on the entry "
        "timeframe, once a confirmation bar shows the trend resuming. Every order has a stop "
        "beyond the recent swing and a target based on risk/reward."
    )
    Params = TrendPullbackParams

    def timeframes(self, params: Any) -> tuple[Timeframe, ...]:
        p: TrendPullbackParams = params
        return (p.entry_timeframe, p.higher_timeframe)

    def required_bars(self, params: Any) -> dict[Timeframe, int]:
        p: TrendPullbackParams = params
        return {p.entry_timeframe: p.ltf_window(), p.higher_timeframe: p.htf_window()}

    def evaluate(self, view: MarketView, params: Any) -> Evaluation:
        p: TrendPullbackParams = params
        ltf = list(view.candles(p.entry_timeframe))[-p.ltf_window() :]
        htf = list(view.candles(p.higher_timeframe))[-p.htf_window() :]
        bar_time = ltf[-1].time if ltf else None
        if len(ltf) < p.ltf_window() or len(htf) < p.htf_window():
            return Evaluation(
                Outcome.INSUFFICIENT_DATA,
                f"Need {p.ltf_window()} {p.entry_timeframe} and {p.htf_window()} "
                f"{p.higher_timeframe} closed bars (have {len(ltf)} / {len(htf)}).",
                bar_time,
            )
        digits = view.symbol.digits

        def fmt(value: float) -> str:
            return f"{value:.{digits}f}"

        h_close = np.array([float(c.close) for c in htf])
        h_high = np.array([float(c.high) for c in htf])
        h_low = np.array([float(c.low) for c in htf])
        h_fast, h_slow = ema(h_close, p.ema_fast), ema(h_close, p.ema_slow)
        checks: list[Check] = []

        def trend_checks(side: Side) -> list[Check]:
            s = side.sign
            out = [
                Check(
                    f"{side.value}: HTF close vs EMA{p.ema_slow}",
                    (h_close[-1] - h_slow[-1]) * s > 0,
                    f"{p.higher_timeframe} close {fmt(h_close[-1])} "
                    f"vs EMA{p.ema_slow} {fmt(h_slow[-1])}",
                ),
            ]
            if p.require_fast_above_slow:
                out.append(
                    Check(
                        f"{side.value}: HTF EMA{p.ema_fast} vs EMA{p.ema_slow}",
                        (h_fast[-1] - h_slow[-1]) * s > 0,
                        f"EMA{p.ema_fast} {fmt(h_fast[-1])} vs EMA{p.ema_slow} {fmt(h_slow[-1])}",
                    )
                )
            if p.require_slope:
                slope = h_slow[-1] - h_slow[-1 - p.slope_lookback]
                out.append(
                    Check(
                        f"{side.value}: HTF EMA{p.ema_slow} slope",
                        slope * s > 0,
                        f"change over {p.slope_lookback} bars: {slope:+.{digits}f}",
                    )
                )
            if p.use_structure:
                highs, lows = swing_points(h_high, h_low)
                ok = (
                    len(highs) >= 2
                    and len(lows) >= 2
                    and (
                        (h_high[highs[-1]] - h_high[highs[-2]]) * s > 0
                        and (h_low[lows[-1]] - h_low[lows[-2]]) * s > 0
                    )
                )
                out.append(
                    Check(
                        f"{side.value}: HTF market structure",
                        ok,
                        "higher highs & higher lows" if s > 0 else "lower highs & lower lows",
                    )
                )
            return out

        long_checks = trend_checks(Side.BUY) if p.allow_long else []
        short_checks = trend_checks(Side.SELL) if p.allow_short else []
        if long_checks and all(c.passed for c in long_checks):
            side = Side.BUY
            checks.extend(long_checks)
        elif short_checks and all(c.passed for c in short_checks):
            side = Side.SELL
            checks.extend(short_checks)
        else:
            checks.extend(long_checks + short_checks)
            return Evaluation(
                Outcome.NO_SETUP, "No clear higher-timeframe trend.", bar_time, checks
            )

        s = side.sign
        close = np.array([float(c.close) for c in ltf])
        open_ = np.array([float(c.open) for c in ltf])
        high = np.array([float(c.high) for c in ltf])
        low = np.array([float(c.low) for c in ltf])
        fast = ema(close, p.ema_fast)
        a = atr(high, low, close, p.atr_period)
        cur_atr = float(a[-1])
        if not np.isfinite(cur_atr) or cur_atr <= 0:
            return Evaluation(Outcome.INSUFFICIENT_DATA, "ATR not available yet.", bar_time, checks)

        # 2. Pullback: within the last N bars (before the signal bar), price
        #    came back to the fast EMA.
        window = slice(-1 - p.pullback_lookback, -1)
        if side is Side.BUY:
            touch = low[window] - (fast[window] + p.pullback_zone_atr * cur_atr)
            depth = (fast[window] - low[window]).max() / cur_atr
        else:
            touch = (fast[window] - p.pullback_zone_atr * cur_atr) - high[window]
            depth = (high[window] - fast[window]).max() / cur_atr
        pulled_back = bool((touch <= 0).any())
        checks.append(
            Check(
                "Pullback to EMA",
                pulled_back,
                f"price came within {p.pullback_zone_atr} ATR of EMA{p.ema_fast} "
                f"in the last {p.pullback_lookback} bars"
                if pulled_back
                else f"no touch of EMA{p.ema_fast} zone in the last {p.pullback_lookback} bars",
            )
        )
        not_too_deep = depth <= p.max_pullback_atr
        checks.append(
            Check(
                "Pullback not too deep",
                bool(not_too_deep),
                f"deepest move beyond EMA{p.ema_fast}: {depth:.2f} ATR (max {p.max_pullback_atr})",
            )
        )

        # 3. Don't chase.
        extension = (close[-1] - fast[-1]) * s / cur_atr
        checks.append(
            Check(
                "Not over-extended",
                bool(extension <= p.max_extension_atr),
                f"close is {extension:.2f} ATR from EMA{p.ema_fast} (max {p.max_extension_atr})",
            )
        )

        # 4. Confirmation on the signal bar.
        if p.confirmation == "close_beyond_prev_extreme":
            confirmed = (close[-1] > high[-2]) if s > 0 else (close[-1] < low[-2])
            detail = "close beyond the previous bar's " + ("high" if s > 0 else "low")
        elif p.confirmation == "trend_close":
            confirmed = (close[-1] - open_[-1]) * s > 0 and (close[-1] - fast[-1]) * s > 0
            detail = f"{'bullish' if s > 0 else 'bearish'} bar closing beyond EMA{p.ema_fast}"
        else:
            confirmed = (
                (close[-1] - open_[-1]) * s > 0
                and (open_[-2] - close[-2]) * s > 0
                and (close[-1] - open_[-2]) * s >= 0
                and (open_[-1] - close[-2]) * s <= 0
            )
            detail = f"{'bullish' if s > 0 else 'bearish'} engulfing bar"
        checks.append(Check("Confirmation", bool(confirmed), detail))

        if not all(c.passed for c in checks):
            failed = next(c for c in checks if not c.passed)
            return Evaluation(
                Outcome.NO_SETUP,
                f"{side.value} trend, but {failed.name.lower()} not met.",
                bar_time,
                checks,
            )

        # 5. Stop and target.
        entry = close[-1]
        if p.stop_mode == "swing":
            span = slice(-p.swing_lookback, None)
            stop = (
                (low[span].min() - p.stop_buffer_atr * cur_atr)
                if s > 0
                else (high[span].max() + p.stop_buffer_atr * cur_atr)
            )
        else:
            stop = entry - s * p.stop_atr_mult * cur_atr
        risk = (entry - stop) * s
        if risk <= 0:
            checks.append(Check("Valid stop", False, "stop is not beyond the entry price"))
            return Evaluation(Outcome.NO_SETUP, "Invalid stop placement.", bar_time, checks)
        target = entry + s * (
            p.reward_risk * risk if p.take_profit_mode == "rr" else p.tp_atr_mult * cur_atr
        )
        checks.append(
            Check(
                "Stop & target",
                True,
                f"stop {fmt(stop)} ({risk / cur_atr:.2f} ATR), target {fmt(target)}",
            )
        )

        quant = Decimal(1).scaleb(-digits)

        def dec(value: float) -> Decimal:
            return Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)

        reasons = [c.detail for c in checks if c.passed]
        signal = SignalIntent(
            side=side,
            timeframe=p.entry_timeframe,
            bar_time=ltf[-1].time,
            entry_price=dec(entry),
            stop_loss=dec(stop),
            take_profit=dec(target),
            reasons=reasons,
        )
        return Evaluation(
            Outcome.SIGNAL,
            f"{side.value} signal: {p.higher_timeframe} trend, "
            f"pullback to EMA{p.ema_fast}, confirmed.",
            bar_time,
            checks,
            signal,
        )
