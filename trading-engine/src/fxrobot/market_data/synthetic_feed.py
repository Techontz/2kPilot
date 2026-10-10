"""Random-access SYNTHETIC 1-minute feed that drives Paper accounts.

Every 1-minute bar is a pure function of (seed, symbol, time): it does not
depend on when the engine started, which bars were requested before, or
today's date. So a Paper account's prices never change after a restart, any
timeframe from M1 to D1 can be built from the same minutes, and quotes,
SL/TP checks and Rise/Fall settlement all read the very same bars.

How it is built (still NOT market data — labelled SYNTHETIC everywhere):

* A **daily path** of log prices from a fixed epoch (2000-01-03): fat-tailed
  daily returns, trending/ranging regimes of a few days, volatility
  clustering and a gentle pull towards the start price.
* **Each day's minutes** are a Brownian bridge from that day's open to the
  next day's open, seeded by (seed, symbol, day), with more movement during
  the London/New York hours. FX symbols hide the weekend minutes (so Monday
  can open with a gap); volatility indices trade around the clock.

Higher timeframes are aggregated with numpy from the 1-minute bars; the
result is identical to `resample()` on the 1-minute candles (tested).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np

from fxrobot.domain.market import Candle, Timeframe
from fxrobot.market_data.sessions import is_fx_market_open
from fxrobot.market_data.synthetic import SyntheticSpec

FEED_EPOCH = datetime(2000, 1, 3, tzinfo=UTC)  # a Monday, aligned to every timeframe
MINUTES = 1440
_DAILY_BLOCK = 512  # days generated per seeded block of the daily path
_DAY_CACHE = 16  # raw 1-minute days kept per symbol
_AGG_CACHE = 4096  # aggregated (day, timeframe) blocks kept per symbol

_MINUTE_OF_DAY = np.arange(MINUTES)
_HOUR = _MINUTE_OF_DAY / 60.0
# Busier London/New York hours; normalised so the day's variance is unchanged.
_SEASON = 1.0 + 0.6 * np.exp(-(((_HOUR - 13.5) / 3.5) ** 2))
_SEASON = _SEASON / np.sqrt(np.mean(_SEASON**2))


def _rng(*parts: object) -> np.random.Generator:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _fx_open_mask(day_start: datetime) -> np.ndarray:
    """Which minutes of the day the FX market is open (Sun 21:00 – Fri 21:00 UTC)."""
    weekday = day_start.weekday()
    mask = np.ones(MINUTES, dtype=bool)
    if weekday == 5:  # Saturday
        mask[:] = False
    elif weekday == 4:  # Friday: closes at 21:00
        mask[21 * 60 :] = False
    elif weekday == 6:  # Sunday: opens at 21:00
        mask[: 21 * 60] = False
    return mask


class _Agg:
    """Aggregated bars of one day for one timeframe (only buckets with open minutes)."""

    __slots__ = ("close", "high", "low", "open", "spread", "start", "volume")

    def __init__(
        self,
        start: np.ndarray,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        spread: np.ndarray,
    ) -> None:
        self.start, self.open, self.high, self.low = start, open_, high, low
        self.close, self.volume, self.spread = close, volume, spread


class SyntheticFeed:
    """Deterministic 1-minute bars for one symbol, available for any time after 2000-01-03."""

    def __init__(self, spec: SyntheticSpec, seed: int) -> None:
        self.spec = spec
        self.seed = seed
        self._quant = Decimal(1).scaleb(-spec.digits)
        self._log0 = float(np.log(spec.start_price))
        self._levels = np.empty(0)  # log price at the start of each day
        self._vols = np.empty(0)  # that day's volatility factor
        self._days: OrderedDict[int, tuple[np.ndarray, ...]] = OrderedDict()
        self._aggs: OrderedDict[tuple[int, Timeframe], _Agg] = OrderedDict()

    # ── daily path ───────────────────────────────────────────────────────
    def _extend_daily(self, day: int) -> None:
        """Make sure the daily path covers days 0 … day + 1 (the bridge needs the next open)."""
        need = day + 2
        if len(self._levels) >= need:
            return
        blocks = -(-need // _DAILY_BLOCK)
        levels = np.empty(blocks * _DAILY_BLOCK + 1)
        vols = np.empty(blocks * _DAILY_BLOCK)
        level, drift, vol, regime_left = self._log0, 0.0, 1.0, 0
        daily_vol = self.spec.daily_vol
        levels[0] = level
        for b in range(blocks):
            rng = _rng(self.seed, self.spec.symbol, "daily", b)
            z = rng.standard_t(df=4, size=_DAILY_BLOCK) / np.sqrt(2.0)
            regime_len = rng.exponential(5.0, size=_DAILY_BLOCK)
            drifts = rng.choice([-0.5, -0.25, 0.0, 0.25, 0.5], size=_DAILY_BLOCK)
            vol_draw = rng.uniform(0.7, 1.35, size=_DAILY_BLOCK)
            for i in range(_DAILY_BLOCK):
                d = b * _DAILY_BLOCK + i
                if regime_left <= 0:
                    regime_left = int(regime_len[i]) + 1
                    drift, vol = float(drifts[i]), float(vol_draw[i])
                regime_left -= 1
                pull = -0.03 * (level - self._log0)
                level += pull + (drift + float(z[i])) * daily_vol * vol
                vols[d] = vol
                levels[d + 1] = level
        self._levels, self._vols = levels, vols

    # ── one day of minutes ───────────────────────────────────────────────
    def _day(self, day: int) -> tuple[np.ndarray, ...]:
        """(open, high, low, close, open_mask) floats for the 1440 minutes of `day`."""
        cached = self._days.get(day)
        if cached is not None:
            self._days.move_to_end(day)
            return cached
        self._extend_daily(day)
        start_level, end_level = float(self._levels[day]), float(self._levels[day + 1])
        sigma = self.spec.daily_vol * float(self._vols[day]) / np.sqrt(MINUTES)
        rng = _rng(self.seed, self.spec.symbol, "day", day)
        z = rng.standard_t(df=4, size=MINUTES) / np.sqrt(2.0)
        wick = np.abs(rng.normal(0.0, 0.6, size=(2, MINUTES)))
        season = np.ones(MINUTES) if self.spec.always_open else _SEASON
        steps = z * season * sigma
        walk = np.cumsum(steps)
        frac = (_MINUTE_OF_DAY + 1) / MINUTES
        path = start_level + walk + frac * ((end_level - start_level) - walk[-1])
        close = np.exp(path)
        open_ = np.empty(MINUTES)
        open_[0] = np.exp(start_level)
        open_[1:] = close[:-1]
        local = sigma * season
        high = np.maximum(open_, close) * (1 + wick[0] * local)
        low = np.minimum(open_, close) * (1 - wick[1] * local)
        day_start = FEED_EPOCH + timedelta(days=day)
        mask = np.ones(MINUTES, dtype=bool) if self.spec.always_open else _fx_open_mask(day_start)
        result = (open_, high, low, close, mask)
        self._days[day] = result
        if len(self._days) > _DAY_CACHE:
            self._days.popitem(last=False)
        return result

    # ── public API ───────────────────────────────────────────────────────
    def spread_points(self, hour: int) -> int:
        # Spreads widen around the daily rollover (~21:00–22:00 UTC).
        return self.spec.spread_points * (3 if hour == 21 else 1)

    def is_open(self, moment: datetime) -> bool:
        return self.spec.always_open or is_fx_market_open(moment)

    def _d(self, value: float) -> Decimal:
        return Decimal(repr(float(value))).quantize(self._quant)

    def bar(self, moment: datetime) -> Candle | None:
        """The 1-minute bar opening at `moment` (floored), or None when the market is closed."""
        moment = Timeframe.M1.floor(moment)
        offset = int((moment - FEED_EPOCH).total_seconds()) // 60
        if offset < 0:
            return None
        day, minute = divmod(offset, MINUTES)
        o, h, lo, c, mask = self._day(day)
        if not mask[minute]:
            return None
        return Candle(
            time=moment,
            open=self._d(o[minute]),
            high=self._d(h[minute]),
            low=self._d(lo[minute]),
            close=self._d(c[minute]),
            tick_volume=1,
            spread_points=self.spread_points(minute // 60),
        )

    def last_bar_before(self, moment: datetime) -> Candle | None:
        """The latest 1-minute bar that closed at or before `moment` (skips the FX weekend)."""
        last = Timeframe.M1.floor(moment) - Timeframe.M1.delta
        if not self.is_open(last):
            # FX: the last open minute is Friday 20:59 UTC.
            friday = last - timedelta(days=(last.weekday() - 4) % 7)
            last = friday.replace(hour=20, minute=59, second=0, microsecond=0)
        return self.bar(last)

    def _aggregate(self, day: int, timeframe: Timeframe) -> _Agg:
        key = (day, timeframe)
        cached = self._aggs.get(key)
        if cached is not None:
            self._aggs.move_to_end(key)
            return cached
        o, h, lo, c, mask = self._day(day)
        per = timeframe.seconds // 60
        idx = np.nonzero(mask)[0]
        if len(idx) == 0:
            empty = np.empty(0)
            agg = _Agg(np.empty(0, dtype=np.int64), empty, empty, empty, empty, empty, empty)
        else:
            bucket = idx // per
            first = np.concatenate(([0], np.nonzero(np.diff(bucket))[0] + 1))
            last = np.concatenate((first[1:] - 1, [len(idx) - 1]))
            spread = np.array(
                [
                    max(self.spread_points(hr) for hr in range(int(h0), int(h1) + 1))
                    for h0, h1 in zip(idx[first] // 60, idx[last] // 60, strict=True)
                ]
            )
            agg = _Agg(
                start=bucket[first] * per,
                open_=o[idx[first]],
                high=np.maximum.reduceat(h[idx], first),
                low=np.minimum.reduceat(lo[idx], first),
                close=c[idx[last]],
                volume=(last - first + 1).astype(float),
                spread=spread.astype(float),
            )
        self._aggs[key] = agg
        if len(self._aggs) > _AGG_CACHE:
            self._aggs.popitem(last=False)
        return agg

    def bars(self, timeframe: Timeframe, start: datetime, end: datetime) -> list[Candle]:
        """Complete `timeframe` bars with open time in [start, end).

        A bar is included only when its whole period lies before `end`, so a
        caller passing the simulated "now" never sees a bar that has not closed.
        Equal to `resample()` of the 1-minute bars over the same period.
        """
        if timeframe is Timeframe.M1:
            first = Timeframe.M1.floor(start)
            if first < start:
                first += Timeframe.M1.delta
            out: list[Candle] = []
            moment = max(first, FEED_EPOCH)
            while moment + Timeframe.M1.delta <= end:
                candle = self.bar(moment)
                if candle is not None:
                    out.append(candle)
                moment += Timeframe.M1.delta
            return out
        lo_day = max(0, int((start - FEED_EPOCH).total_seconds()) // 86400)
        hi_day = int((end - FEED_EPOCH).total_seconds() - 1) // 86400
        out = []
        for day in range(lo_day, hi_day + 1):
            agg = self._aggregate(day, timeframe)
            day_start = FEED_EPOCH + timedelta(days=day)
            for i in range(len(agg.start)):
                moment = day_start + timedelta(minutes=int(agg.start[i]))
                if moment < start or moment + timeframe.delta > end:
                    continue
                out.append(
                    Candle(
                        time=moment,
                        open=self._d(agg.open[i]),
                        high=self._d(agg.high[i]),
                        low=self._d(agg.low[i]),
                        close=self._d(agg.close[i]),
                        tick_volume=int(agg.volume[i]),
                        spread_points=int(agg.spread[i]),
                    )
                )
        return out
