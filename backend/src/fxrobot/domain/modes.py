"""Operating modes. LIVE is never entered implicitly — see services/trading_control."""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    BACKTEST = "BACKTEST"  # historical simulation only; no broker orders
    DEMO = "DEMO"  # orders may go to broker DEMO accounts only
    LIVE = "LIVE"  # real money — requires hard lock off + deliberate activation


class AccountEnvironment(StrEnum):
    DEMO = "DEMO"
    LIVE = "LIVE"
    # The broker did not tell us. Must be treated as LIVE for every safety check.
    UNKNOWN = "UNKNOWN"

    @property
    def is_real_money_possible(self) -> bool:
        return self is not AccountEnvironment.DEMO
