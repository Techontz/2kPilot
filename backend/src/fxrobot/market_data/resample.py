"""Aggregate lower-timeframe candles into higher timeframes without look-ahead."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from fxrobot.domain.market import Candle, Timeframe


def resample(
    candles: Sequence[Candle], target: Timeframe, *, until: datetime | None = None
) -> list[Candle]:
    """Resample `candles` (sorted, any lower timeframe) into `target` bars.

    A target bar is emitted only when its whole period has ended by `until`
    (or, without `until`, when a later source bar proves it ended). This is
    what prevents a strategy from seeing a higher-timeframe bar that has not
    closed yet.
    """
    result: list[Candle] = []
    bucket: list[Candle] = []
    bucket_start: datetime | None = None
    for candle in candles:
        start = target.floor(candle.time)
        if bucket_start is not None and start != bucket_start:
            result.append(_merge(bucket_start, bucket))
            bucket = []
        bucket_start = start
        bucket.append(candle)
    last_closed = (
        until is not None and bucket_start is not None and bucket_start + target.delta <= until
    )
    if bucket and bucket_start is not None and last_closed:
        result.append(_merge(bucket_start, bucket))
    return result


def _merge(start: datetime, bars: list[Candle]) -> Candle:
    spreads = [b.spread_points for b in bars if b.spread_points is not None]
    return Candle(
        time=start,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        tick_volume=sum(b.tick_volume for b in bars),
        spread_points=max(spreads) if spreads else None,
    )
