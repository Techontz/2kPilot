from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

from fxrobot.domain.market import Candle, Side, SymbolInfo, Timeframe
from fxrobot.domain.trading import OrderType


class Outcome(StrEnum):
    SIGNAL = "SIGNAL"
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class Check:
    """One condition the strategy evaluated — the building block of explanations."""

    name: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "passed", bool(self.passed))  # numpy bools → bool

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class SignalIntent:
    side: Side
    timeframe: Timeframe
    bar_time: datetime  # open time of the closed bar that produced the signal
    entry_price: Decimal  # reference price (signal bar close); actual fill may differ
    stop_loss: Decimal
    take_profit: Decimal | None
    reasons: list[str]
    entry_type: OrderType = OrderType.MARKET

    @property
    def risk_distance(self) -> Decimal:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_risk(self) -> Decimal | None:
        if self.take_profit is None or self.risk_distance == 0:
            return None
        return abs(self.take_profit - self.entry_price) / self.risk_distance


@dataclass(frozen=True)
class Evaluation:
    outcome: Outcome
    summary: str
    bar_time: datetime | None
    checks: list[Check] = field(default_factory=list)
    signal: SignalIntent | None = None

    def checks_json(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.checks]


class MarketView(Protocol):
    """What a strategy may see: CLOSED candles only, as of the decision time."""

    symbol: SymbolInfo

    def candles(self, timeframe: Timeframe) -> Sequence[Candle]: ...


class Strategy(ABC):
    key: ClassVar[str]
    name: ClassVar[str]
    code_version: ClassVar[str]
    description: ClassVar[str]
    Params: ClassVar[type[BaseModel]]

    def parse_params(self, raw: dict[str, Any]) -> BaseModel:
        return self.Params.model_validate(raw)

    def default_params(self) -> dict[str, Any]:
        return self.Params().model_dump(mode="json")

    @abstractmethod
    def timeframes(self, params: Any) -> tuple[Timeframe, ...]:
        """(entry timeframe, *context timeframes). The entry timeframe drives evaluation."""

    @abstractmethod
    def required_bars(self, params: Any) -> dict[Timeframe, int]:
        """Minimum history per timeframe for a meaningful evaluation."""

    @abstractmethod
    def evaluate(self, view: MarketView, params: Any) -> Evaluation: ...
