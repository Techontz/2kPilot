"""Candle data validation: ordering, duplicates, OHLC sanity, gaps, spikes.

Malformed data is never silently used. `clean_candles` drops bars that are
internally inconsistent and reports exactly what it dropped.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fxrobot.domain.market import Candle, Timeframe
from fxrobot.market_data.sessions import is_fx_market_open


@dataclass
class Gap:
    start: datetime  # first missing bar open time
    missing_bars: int


@dataclass
class ValidationReport:
    bar_count: int = 0
    invalid_bars: list[str] = field(default_factory=list)
    duplicates: int = 0
    out_of_order: int = 0
    gaps: list[Gap] = field(default_factory=list)
    spikes: list[datetime] = field(default_factory=list)
    misaligned: int = 0

    @property
    def missing_bars(self) -> int:
        return sum(g.missing_bars for g in self.gaps)

    @property
    def is_clean(self) -> bool:
        return not (self.invalid_bars or self.duplicates or self.out_of_order or self.misaligned)

    def summary(self) -> dict[str, object]:
        return {
            "bars": self.bar_count,
            "invalid": len(self.invalid_bars),
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "misaligned": self.misaligned,
            "gaps": len(self.gaps),
            "missing_bars": self.missing_bars,
            "spikes": len(self.spikes),
        }


def bar_problem(candle: Candle) -> str | None:
    """Why a single bar is internally inconsistent, or None if it is fine."""
    values = (candle.open, candle.high, candle.low, candle.close)
    if any(v <= 0 for v in values):
        return "non-positive price"
    if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
        return "high/low do not contain open/close"
    if candle.high < candle.low:
        return "high below low"
    if candle.tick_volume < 0:
        return "negative volume"
    if candle.time.tzinfo is None:
        return "naive timestamp"
    return None


def validate_candles(
    candles: Sequence[Candle], timeframe: Timeframe, *, spike_factor: float = 12.0
) -> ValidationReport:
    report = ValidationReport(bar_count=len(candles))
    previous: datetime | None = None
    ranges: list[tuple[datetime, float]] = []
    for candle in candles:
        problem = bar_problem(candle)
        if problem:
            report.invalid_bars.append(f"{candle.time.isoformat()}: {problem}")
            continue
        if timeframe.floor(candle.time) != candle.time:
            report.misaligned += 1
        if previous is not None:
            if candle.time == previous:
                report.duplicates += 1
                continue
            if candle.time < previous:
                report.out_of_order += 1
                continue
            missing = _missing_bars(previous, candle.time, timeframe)
            if missing:
                report.gaps.append(Gap(previous + timeframe.delta, missing))
        previous = candle.time
        ranges.append((candle.time, float(candle.high - candle.low)))
    if len(ranges) >= 20:
        median = statistics.median(r for _, r in ranges) or 0.0
        if median > 0:
            report.spikes = [t for t, r in ranges if r > spike_factor * median]
    return report


def _missing_bars(previous: datetime, current: datetime, timeframe: Timeframe) -> int:
    """Expected-but-absent bars between two bars, ignoring the weekend closure."""
    step = timeframe.delta
    if current - previous <= step:
        return 0
    if timeframe is Timeframe.D1:
        # Daily bars: count missing weekdays only.
        missing, cursor = 0, previous + step
        while cursor < current:
            if cursor.weekday() < 5:
                missing += 1
            cursor += step
        return missing
    missing, cursor = 0, previous + step
    limit = 10_000
    while cursor < current and limit:
        # A bar is expected if the market is open at any point during it.
        if is_fx_market_open(cursor) or is_fx_market_open(cursor + step - timedelta(seconds=1)):
            missing += 1
        cursor += step
        limit -= 1
    return missing


def clean_candles(candles: Sequence[Candle]) -> tuple[list[Candle], list[str]]:
    """Sort, de-duplicate (last wins) and drop inconsistent bars."""
    dropped: list[str] = []
    by_time: dict[datetime, Candle] = {}
    for candle in candles:
        problem = bar_problem(candle)
        if problem:
            dropped.append(f"{candle.time.isoformat()}: {problem}")
            continue
        by_time[candle.time] = candle
    return [by_time[t] for t in sorted(by_time)], dropped


def is_stale(last_update: datetime, now: datetime, max_age_seconds: float) -> bool:
    return (now - last_update).total_seconds() > max_age_seconds
