"""Simulated markets that drive the PAPER broker.

* `SyntheticMarket` — generated prices (clearly labelled SYNTHETIC).
* `ReplayMarket` — replays a stored historical dataset bar by bar.

Simulated time advances in base-timeframe steps, accelerated by
`seconds_per_bar`, and NEVER runs ahead of real wall-clock time: once the
simulation catches up with the present it continues in real time.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fxrobot.domain.market import Candle, Quote, SymbolInfo, Timeframe
from fxrobot.market_data.resample import resample
from fxrobot.market_data.sessions import is_fx_market_open
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries

WallClock = Callable[[], float]
UtcNow = Callable[[], datetime]

MAX_STEPS_PER_ADVANCE = 200


class SimMarket(ABC):
    base_timeframe: Timeframe
    label: str  # "SYNTHETIC" | "REPLAY"

    def __init__(
        self,
        base_timeframe: Timeframe,
        cursor: datetime,
        seconds_per_bar: float,
        *,
        wall_clock: WallClock = time.monotonic,
        utcnow: UtcNow = lambda: datetime.now(UTC),
    ) -> None:
        self.base_timeframe = base_timeframe
        self.cursor = base_timeframe.floor(cursor)  # simulated "now" (a bar boundary)
        self.seconds_per_bar = max(0.0, seconds_per_bar)
        self._wall = wall_clock
        self._utcnow = utcnow
        self._last_step_wall = wall_clock()
        self._cache: dict[tuple[str, Timeframe, datetime], list[Candle]] = {}

    # ── required by subclasses ───────────────────────────────────────────
    @abstractmethod
    def symbols(self) -> list[SymbolInfo]: ...

    @abstractmethod
    def base_bars(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        """Base bars with open time in [start, end) — may include future bars; callers cap."""

    @abstractmethod
    def exhausted(self) -> bool:
        """True when no further bars can be produced (end of a replay)."""

    # ── time ─────────────────────────────────────────────────────────────
    def now(self) -> datetime:
        return self.cursor

    def is_open(self) -> bool:
        return not self.exhausted() and is_fx_market_open(self.cursor)

    def advance(self) -> list[tuple[str, Candle]]:
        """Advance according to wall-clock pacing. Returns newly completed base bars."""
        if self.seconds_per_bar <= 0:
            return []
        elapsed = self._wall() - self._last_step_wall
        steps = int(elapsed // self.seconds_per_bar)
        if steps <= 0:
            return []
        self._last_step_wall += steps * self.seconds_per_bar
        return self.step(min(steps, MAX_STEPS_PER_ADVANCE))

    def step(self, bars: int = 1) -> list[tuple[str, Candle]]:
        """Move forward `bars` base bars (never past real time). Returns completed bars."""
        completed: list[tuple[str, Candle]] = []
        start_cursor = self.cursor
        limit = self.base_timeframe.floor(self._utcnow())
        for _ in range(bars):
            if self.exhausted():
                break
            nxt = self.cursor + self.base_timeframe.delta
            if nxt > limit:
                break  # caught up with real time
            for symbol in self.symbols():
                bar = self.base_bars(symbol.name, self.cursor, nxt)
                if bar:
                    completed.append((symbol.name, bar[0]))
            self.cursor = nxt
        if self.cursor != start_cursor:
            self._cache.clear()
        return completed

    # ── data ─────────────────────────────────────────────────────────────
    def candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Closed candles in [start, end) as of the simulated now."""
        end = min(end, self.cursor)
        if end <= start:
            return []
        key = (symbol, timeframe, start)
        if key in self._cache and end == self.cursor:
            return self._cache[key]
        base_start = timeframe.floor(start)
        base = self.base_bars(symbol, base_start, end)
        if timeframe is self.base_timeframe:
            result = [c for c in base if start <= c.time < end]
        else:
            result = [
                c for c in resample(base, timeframe, until=self.cursor) if start <= c.time < end
            ]
        if end == self.cursor:
            self._cache[key] = result
        return result

    def last_bar(self, symbol: str) -> Candle | None:
        lookback = self.cursor - timedelta(days=5)
        bars = self.base_bars(symbol, lookback, self.cursor)
        return bars[-1] if bars else None

    def quote(self, symbol: str, spec: SymbolInfo) -> Quote | None:
        bar = self.last_bar(symbol)
        if bar is None:
            return None
        spread = Decimal(bar.spread_points or 0) * spec.point
        return Quote(symbol=symbol, bid=bar.close, ask=bar.close + spread, time=self.cursor)

    def state(self) -> dict[str, Any]:
        return {"cursor": self.cursor.isoformat()}


class SyntheticMarket(SimMarket):
    label = "SYNTHETIC"

    def __init__(
        self,
        *,
        seed: int,
        symbols: Sequence[str],
        start: datetime,
        seconds_per_bar: float,
        base_timeframe: Timeframe = Timeframe.M15,
        history_days: int = 120,
        wall_clock: WallClock = time.monotonic,
        utcnow: UtcNow = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            base_timeframe, start, seconds_per_bar, wall_clock=wall_clock, utcnow=utcnow
        )
        origin = self.cursor - timedelta(days=history_days)
        unknown = [s for s in symbols if s not in DEFAULT_SPECS]
        if unknown:
            raise ValueError(f"no synthetic spec for {', '.join(unknown)}")
        self.series = {
            s: SyntheticSeries(DEFAULT_SPECS[s], seed, origin, base_timeframe) for s in symbols
        }
        self._symbols = [DEFAULT_SPECS[s].symbol_info() for s in symbols]

    def symbols(self) -> list[SymbolInfo]:
        return self._symbols

    def base_bars(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        series = self.series.get(symbol)
        return series.bars(start, end) if series else []

    def exhausted(self) -> bool:
        return False


class ReplayMarket(SimMarket):
    """Replays stored candles (e.g. imported real history) as a live market."""

    label = "REPLAY"

    def __init__(
        self,
        *,
        bars: dict[str, list[Candle]],
        specs: dict[str, SymbolInfo],
        base_timeframe: Timeframe,
        start: datetime,
        seconds_per_bar: float,
        wall_clock: WallClock = time.monotonic,
        utcnow: UtcNow = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            base_timeframe, start, seconds_per_bar, wall_clock=wall_clock, utcnow=utcnow
        )
        self._bars = bars
        self._specs = specs
        self._times = {s: [c.time for c in b] for s, b in bars.items()}
        self._end = max(
            (b[-1].time + base_timeframe.delta for b in bars.values() if b), default=start
        )

    def symbols(self) -> list[SymbolInfo]:
        return list(self._specs.values())

    def base_bars(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        import bisect

        times = self._times.get(symbol, [])
        lo = bisect.bisect_left(times, start)
        hi = bisect.bisect_left(times, end)
        return self._bars.get(symbol, [])[lo:hi]

    def exhausted(self) -> bool:
        return self.cursor >= self._end
