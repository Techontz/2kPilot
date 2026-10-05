"""Strategy engine: strategies turn closed candles into explainable signals.

Strategies are pure decision functions. They NEVER place orders, size
positions in money, or know which broker is used — the risk engine and the
execution engine do that.
"""

from fxrobot.strategy_engine.base import (
    Check,
    Evaluation,
    MarketView,
    Outcome,
    SignalIntent,
    Strategy,
)
from fxrobot.strategy_engine.registry import get_strategy, list_strategies

__all__ = [
    "Check",
    "Evaluation",
    "MarketView",
    "Outcome",
    "SignalIntent",
    "Strategy",
    "get_strategy",
    "list_strategies",
]
