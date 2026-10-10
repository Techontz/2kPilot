"""Deterministic SYNTHETIC price generator — for development and tests only.

This is NOT market data. It produces plausible-looking FX bars (fat-tailed
returns, trending/ranging regimes, volatility clustering, weekend closure)
so the whole pipeline can be exercised without a broker. It can also imitate
the SHAPE of a volatility index that trades around the clock (R_10 … R_100:
constant annualised volatility of 10 … 100 %) — generated here, NOT Deriv's
feed. Everything built
on it is labelled SYNTHETIC / PAPER in the database and the UI, and results
on it say nothing about real markets.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np

from fxrobot.domain.market import Candle, SymbolInfo, Timeframe
from fxrobot.market_data.sessions import is_fx_market_open

_CHUNK = 4096


@dataclass(frozen=True)
class SyntheticSpec:
    symbol: str
    base: str
    quote: str
    start_price: float
    digits: int
    daily_vol: float  # relative, e.g. 0.005 = 0.5 % per day
    spread_points: int
    contract_size: int = 100_000
    always_open: bool = False  # trades 24/7 (volatility indices), no FX weekend
    name: str = ""

    def symbol_info(self) -> SymbolInfo:
        point = Decimal(1).scaleb(-self.digits)
        return SymbolInfo(
            name=self.symbol,
            description=(self.name or f"{self.base}/{self.quote}") + " (synthetic)",
            base_currency=self.base,
            quote_currency=self.quote,
            digits=self.digits,
            point=point,
            contract_size=Decimal(self.contract_size),
            volume_min=Decimal("0.01"),
            volume_max=Decimal(50),
            volume_step=Decimal("0.01"),
            trade_allowed=True,
            canonical=self.symbol,
            category="synthetic" if self.always_open else "forex",
            market_open=True if self.always_open else None,
        )


def _index(symbol: str, price: float, digits: int, annual_vol: float, name: str) -> SyntheticSpec:
    """A 24/7 index with constant volatility (the shape of Deriv's volatility indices)."""
    return SyntheticSpec(
        symbol,
        symbol,
        "USD",
        price,
        digits,
        annual_vol / 365**0.5,
        0,
        contract_size=1,
        always_open=True,
        name=name,
    )


DEFAULT_SPECS: dict[str, SyntheticSpec] = {
    s.symbol: s
    for s in (
        SyntheticSpec("EURUSD", "EUR", "USD", 1.0850, 5, 0.0050, 12),
        SyntheticSpec("GBPUSD", "GBP", "USD", 1.2700, 5, 0.0060, 15),
        SyntheticSpec("USDJPY", "USD", "JPY", 150.00, 3, 0.0055, 14),
        SyntheticSpec("AUDUSD", "AUD", "USD", 0.6600, 5, 0.0065, 14),
        SyntheticSpec("USDCHF", "USD", "CHF", 0.8800, 5, 0.0050, 16),
        SyntheticSpec("USDCAD", "USD", "CAD", 1.3600, 5, 0.0045, 18),
        _index("R_10", 6000.0, 3, 0.10, "Volatility 10-like index"),
        _index("R_25", 3000.0, 3, 0.25, "Volatility 25-like index"),
        _index("R_50", 250.0, 4, 0.50, "Volatility 50-like index"),
        _index("R_75", 80000.0, 4, 0.75, "Volatility 75-like index"),
        _index("R_100", 1000.0, 2, 1.00, "Volatility 100-like index"),
    )
}


class SyntheticSeries:
    """Lazily generated base-timeframe bars for one symbol, indexed from `origin`.

    Bar i opens at origin + i * timeframe. Generation is sequential from a
    seeded RNG, so any bar is reproducible given (seed, symbol, origin).
    """

    def __init__(
        self, spec: SyntheticSpec, seed: int, origin: datetime, timeframe: Timeframe = Timeframe.M15
    ) -> None:
        self.spec = spec
        self.timeframe = timeframe
        self.origin = timeframe.floor(origin)
        digest = hashlib.sha256(f"{seed}:{spec.symbol}".encode()).digest()
        self._rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        bars_per_day = 86400 / timeframe.seconds
        self._sigma = spec.daily_vol / np.sqrt(bars_per_day)
        self._open = np.empty(0)
        self._high = np.empty(0)
        self._low = np.empty(0)
        self._close = np.empty(0)
        self._last_close = spec.start_price
        self._regime_left = 0
        self._drift = 0.0
        self._vol_factor = 1.0
        self._quant = Decimal(1).scaleb(-spec.digits)

    def _extend(self, upto: int) -> None:
        while len(self._close) <= upto:
            n = _CHUNK
            opens, highs, lows, closes = (np.empty(n) for _ in range(4))
            z = self._rng.standard_t(df=4, size=n) / np.sqrt(2.0)  # unit-variance fat tails
            wick = np.abs(self._rng.normal(0, 0.6, size=(n, 2)))
            price = self._last_close
            for i in range(n):
                if self._regime_left <= 0:
                    self._regime_left = int(self._rng.exponential(480)) + 48
                    self._drift = float(self._rng.choice([-0.08, -0.04, 0.0, 0.04, 0.08]))
                    self._vol_factor = float(self._rng.uniform(0.7, 1.35))
                self._regime_left -= 1
                sigma = self._sigma * self._vol_factor
                # Gentle pull towards the start price keeps levels plausible over months.
                pull = -0.002 * float(np.log(price / self.spec.start_price)) / sigma
                ret = (self._drift + pull + z[i]) * sigma
                open_ = price
                close = open_ * float(np.exp(ret))
                high = max(open_, close) * (1 + wick[i, 0] * sigma)
                low = min(open_, close) * (1 - wick[i, 1] * sigma)
                opens[i], highs[i], lows[i], closes[i] = open_, high, low, close
                price = close
            self._last_close = price
            self._open = np.concatenate([self._open, opens])
            self._high = np.concatenate([self._high, highs])
            self._low = np.concatenate([self._low, lows])
            self._close = np.concatenate([self._close, closes])

    def index_of(self, moment: datetime) -> int:
        return int((moment - self.origin).total_seconds() // self.timeframe.seconds)

    def time_of(self, index: int) -> datetime:
        return self.origin + timedelta(seconds=index * self.timeframe.seconds)

    def _d(self, value: float) -> Decimal:
        return Decimal(repr(value)).quantize(self._quant)

    def spread_points(self, bar_time: datetime) -> int:
        # Spreads widen around the daily rollover (~21:00–22:00 UTC).
        return self.spec.spread_points * (3 if bar_time.hour == 21 else 1)

    def bar(self, index: int) -> Candle | None:
        """The bar at `index`, or None when the market is closed at that time."""
        if index < 0:
            return None
        moment = self.time_of(index)
        if not self.spec.always_open and not is_fx_market_open(moment):
            return None
        self._extend(index)
        return Candle(
            time=moment,
            open=self._d(float(self._open[index])),
            high=self._d(float(self._high[index])),
            low=self._d(float(self._low[index])),
            close=self._d(float(self._close[index])),
            tick_volume=100,
            spread_points=self.spread_points(moment),
        )

    def bars(self, start: datetime, end: datetime) -> list[Candle]:
        """Base bars with open time in [start, end)."""
        first = max(0, self.index_of(self.timeframe.floor(start)))
        if self.time_of(first) < start:
            first += 1
        last = self.index_of(end - timedelta(microseconds=1))
        out: list[Candle] = []
        for i in range(first, last + 1):
            candle = self.bar(i)
            if candle is not None:
                out.append(candle)
        return out
