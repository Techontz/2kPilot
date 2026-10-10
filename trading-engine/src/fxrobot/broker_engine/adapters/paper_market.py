"""Simulated markets that drive the PAPER broker.

* `SyntheticMarket` — generated prices (clearly labelled SYNTHETIC), built
  from a deterministic 1-minute feed so every timeframe M1 … D1 is available.
* `ReplayMarket` — replays a stored historical dataset bar by bar.

Simulated time advances in base-timeframe steps, accelerated by
`seconds_per_bar` (wall-clock seconds per 15 simulated minutes), and NEVER
runs ahead of real wall-clock time: once the simulation catches up with the
present it continues in real time. The engine may also cap one advance at the
next close of the finest timeframe a strategy watches, so that every candle
of that timeframe is evaluated.

"Real time" comes from `paper_clock()`, which tests pin to a fixed date.
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
from fxrobot.market_data.synthetic import DEFAULT_SPECS
from fxrobot.market_data.synthetic_feed import SyntheticFeed

WallClock = Callable[[], float]
UtcNow = Callable[[], datetime]

MAX_STEPS_PER_ADVANCE = 200
PACE_TIMEFRAME = Timeframe.M15  # `seconds_per_bar` is wall seconds per 15 simulated minutes


def _real_utcnow() -> datetime:
    return datetime.now(UTC)


_clock: UtcNow = _real_utcnow


def paper_clock() -> datetime:
    """'Real' UTC now as seen by paper markets (where a new simulation starts, how
    far it may run). Tests pin it with `set_paper_clock` so they never depend on
    today's date."""
    return _clock()


def set_paper_clock(clock: UtcNow | None) -> None:
    """Replace the paper markets' clock (None restores the real clock)."""
    global _clock
    _clock = clock or _real_utcnow


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
        utcnow: UtcNow = paper_clock,
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

    def is_open(self, symbol: str | None = None) -> bool:
        if self.exhausted():
            return False
        return (symbol is not None and self.always_open(symbol)) or is_fx_market_open(self.cursor)

    def always_open(self, symbol: str) -> bool:
        """True for symbols that trade around the clock (no FX weekend)."""
        return False

    @property
    def seconds_per_step(self) -> float:
        """Wall-clock seconds per base bar (`seconds_per_bar` is per 15 simulated minutes)."""
        return self.seconds_per_bar * self.base_timeframe.seconds / PACE_TIMEFRAME.seconds

    def advance(self, until: datetime | None = None) -> list[tuple[str, Candle]]:
        """Advance according to wall-clock pacing, never past `until` (when given).

        Returns newly completed base bars. When `until` holds the simulation
        back, the extra elapsed wall time is dropped (the simulation slows down
        to one candle of the strategy's timeframe per call).
        """
        if self.seconds_per_bar <= 0:
            return []
        per_step = self.seconds_per_step
        elapsed = self._wall() - self._last_step_wall
        steps = int(elapsed // per_step)
        if steps <= 0:
            return []
        self._last_step_wall += steps * per_step
        if until is not None:
            room = int((until - self.cursor) / self.base_timeframe.delta)
            if room < steps:
                steps = max(0, room)
                self._last_step_wall = self._wall()
        return self.step(min(steps, MAX_STEPS_PER_ADVANCE)) if steps > 0 else []

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
    """Generated prices from `SyntheticFeed`: 1-minute bars by default, any timeframe on request.

    Prices are a pure function of (seed, symbol, time), so they never change
    when the engine restarts or the simulation is resumed.
    """

    label = "SYNTHETIC"

    def __init__(
        self,
        *,
        seed: int,
        symbols: Sequence[str],
        start: datetime,
        seconds_per_bar: float,
        base_timeframe: Timeframe = Timeframe.M1,
        wall_clock: WallClock = time.monotonic,
        utcnow: UtcNow = paper_clock,
    ) -> None:
        super().__init__(
            base_timeframe, start, seconds_per_bar, wall_clock=wall_clock, utcnow=utcnow
        )
        unknown = [s for s in symbols if s not in DEFAULT_SPECS]
        if unknown:
            raise ValueError(f"no synthetic spec for {', '.join(unknown)}")
        self.feeds = {s: SyntheticFeed(DEFAULT_SPECS[s], seed) for s in symbols}
        self._symbols = [DEFAULT_SPECS[s].symbol_info() for s in symbols]

    def symbols(self) -> list[SymbolInfo]:
        return self._symbols

    def always_open(self, symbol: str) -> bool:
        feed = self.feeds.get(symbol)
        return feed is not None and feed.spec.always_open

    def base_bars(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        feed = self.feeds.get(symbol)
        if feed is None:
            return []
        if self.base_timeframe is Timeframe.M1 and end - start <= Timeframe.M1.delta:
            bar = feed.bar(start)  # one simulation step: the cheap path
            return [bar] if bar is not None and start <= bar.time < end else []
        return feed.bars(self.base_timeframe, start, end)

    def candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Closed candles in [start, end) as of the simulated now — any timeframe."""
        feed = self.feeds.get(symbol)
        if feed is None or timeframe.seconds < self.base_timeframe.seconds:
            return []
        end = min(end, self.cursor)
        if end <= start:
            return []
        return feed.bars(timeframe, start, end)

    def last_bar(self, symbol: str) -> Candle | None:
        feed = self.feeds.get(symbol)
        if feed is None:
            return None
        if self.base_timeframe is Timeframe.M1:
            return feed.last_bar_before(self.cursor)
        return super().last_bar(symbol)

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
        utcnow: UtcNow = paper_clock,
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
