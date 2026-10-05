"""Broker-neutral market data types.

Prices use `Decimal`; timestamps are timezone-aware UTC. Adapters convert
broker-native values into these types at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def seconds(self) -> int:
        return _TIMEFRAME_SECONDS[self]

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    def floor(self, moment: datetime) -> datetime:
        """Open time of the bar containing `moment` (bars are aligned to UTC epoch)."""
        epoch = int(moment.timestamp())
        return datetime.fromtimestamp(epoch - epoch % self.seconds, tz=moment.tzinfo)


_TIMEFRAME_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    name: str  # broker symbol, e.g. "EURUSD" or "EURUSD.m"
    description: str
    base_currency: str
    quote_currency: str
    digits: int
    point: Decimal  # smallest price increment
    contract_size: Decimal  # units per 1.00 lot
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    trade_allowed: bool
    # Value of a one-point move for 1.00 lot in the ACCOUNT currency, when the
    # broker provides it (MT5 does). Otherwise computed from conversion rates.
    point_value: Decimal | None = None
    canonical: str | None = None  # "EURUSD" when the broker symbol has a suffix
    # forex | commodities | indices | crypto | synthetic | stocks | other
    category: str = "forex"
    # Broker-reported market status; None = unknown (the FX weekly schedule is used).
    market_open: bool | None = None

    @property
    def pip_size(self) -> Decimal:
        # 5/3-digit quotes use fractional pips: 1 pip = 10 points.
        return self.point * 10 if self.digits in (3, 5) else self.point

    @property
    def canonical_name(self) -> str:
        return self.canonical or self.name


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    time: datetime

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.ask + self.bid) / 2

    def age_seconds(self, now: datetime) -> float:
        return (now - self.time).total_seconds()


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime  # bar open time, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int = 0
    spread_points: int | None = None
