"""MarketView implementations shared by live trading and backtesting."""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from datetime import datetime

from fxrobot.domain.market import Candle, SymbolInfo, Timeframe
from fxrobot.market_data.resample import resample


class StaticView:
    """Pre-fetched closed candles per timeframe (live trading)."""

    def __init__(self, symbol: SymbolInfo, candles: Mapping[Timeframe, Sequence[Candle]]) -> None:
        self.symbol = symbol
        self._candles = candles

    def candles(self, timeframe: Timeframe) -> Sequence[Candle]:
        return self._candles.get(timeframe, [])


class CursorView:
    """Backtest view over full history that only reveals bars closed at `now`.

    Higher timeframes are resampled from the base series and only bars whose
    whole period has ended are visible — the core look-ahead guard.
    """

    def __init__(
        self,
        symbol: SymbolInfo,
        base: Sequence[Candle],
        base_tf: Timeframe,
        timeframes: Sequence[Timeframe],
    ) -> None:
        self.symbol = symbol
        self.base_tf = base_tf
        self._series: dict[Timeframe, list[Candle]] = {base_tf: list(base)}
        for tf in timeframes:
            if tf is not base_tf:
                self._series[tf] = (
                    resample(base, tf, until=base[-1].time + base_tf.delta) if base else []
                )
        self._times = {tf: [c.time for c in s] for tf, s in self._series.items()}
        self.now: datetime | None = None
        self._limits: dict[Timeframe, int] = {}

    def set_time(self, now: datetime) -> None:
        """Only bars with open_time + timeframe <= now are visible."""
        self.now = now
        for tf, times in self._times.items():
            self._limits[tf] = bisect.bisect_right(times, now - tf.delta)

    def candles(self, timeframe: Timeframe) -> Sequence[Candle]:
        if self.now is None:
            return []
        return self._series.get(timeframe, [])[: self._limits.get(timeframe, 0)]
