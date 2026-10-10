"""Catalogue of strategy implementations."""

from __future__ import annotations

from fxrobot.strategy_engine.base import Strategy
from fxrobot.strategy_engine.rules.strategy import RulesStrategy
from fxrobot.strategy_engine.trend_pullback import TrendPullbackV1

_STRATEGIES: dict[str, Strategy] = {s.key: s for s in (TrendPullbackV1(), RulesStrategy())}


def get_strategy(key: str) -> Strategy:
    try:
        return _STRATEGIES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown strategy {key!r}") from exc


def list_strategies() -> list[Strategy]:
    return list(_STRATEGIES.values())
