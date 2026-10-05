"""Operating modes and account environments.

LIVE is never entered implicitly — see services/trading_control.
"""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    BACKTEST = "BACKTEST"  # historical simulation only; no broker orders
    DEMO = "DEMO"  # orders may go to PAPER or broker DEMO accounts only
    LIVE = "LIVE"  # real money — requires hard lock off + deliberate activation


class AccountEnvironment(StrEnum):
    PAPER = "PAPER"  # internal simulator; no broker involved at all
    DEMO = "DEMO"  # broker account funded with virtual money
    LIVE = "LIVE"  # real money
    # The broker did not tell us. Must be treated as LIVE for every safety check.
    UNKNOWN = "UNKNOWN"

    @property
    def is_real_money_possible(self) -> bool:
        return self in (AccountEnvironment.LIVE, AccountEnvironment.UNKNOWN)


def environment_permitted(mode: TradingMode, environment: AccountEnvironment) -> bool:
    """May an account of `environment` receive orders while the system is in `mode`?"""
    if environment is AccountEnvironment.UNKNOWN or mode is TradingMode.BACKTEST:
        return False
    if mode is TradingMode.DEMO:
        return environment in (AccountEnvironment.PAPER, AccountEnvironment.DEMO)
    return True  # LIVE mode: PAPER, DEMO and LIVE accounts
