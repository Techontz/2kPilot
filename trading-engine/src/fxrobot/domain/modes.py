"""Operating modes, account environments and the trading controls that gate them.

Every user has their own STOP switch and mode (Laravel's user_trading_states);
admins have a platform-wide HALT on top. LIVE is never entered implicitly —
Laravel requires MFA, the password and a typed phrase, and records the moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TradingMode(StrEnum):
    DEMO = "DEMO"  # orders may go to PAPER or broker DEMO accounts only
    LIVE = "LIVE"  # real money: LIVE accounts only — hard lock off + deliberate activation


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
    """May an account of `environment` receive orders while its owner is in `mode`?

    DEMO mode trades PAPER and DEMO accounts; LIVE mode trades LIVE accounts only.
    """
    if mode is TradingMode.DEMO:
        return environment in (AccountEnvironment.PAPER, AccountEnvironment.DEMO)
    return environment is AccountEnvironment.LIVE


NOT_AUTHORISED = "LIVE trading has not been authorised by the account owner"
AUTHORISATION_MISMATCH = "Real-money authorization doesn't cover this account/limits — re-authorize"


@dataclass(frozen=True)
class TradingControls:
    """The switches that apply to one account at one moment.

    Built from the platform row (system_state) and the account owner's
    user_trading_states row; passed into the pure risk engine.
    """

    platform_halted: bool  # admin emergency halt: nobody trades
    kill_switch_engaged: bool  # the owner's own STOP switch
    mode: TradingMode  # the owner's operating mode
    live_authorized: bool  # the owner's LIVE authorisation covers THIS account and its limits
    live_trading_locked: bool  # server hard lock (LIVE_TRADING_ENABLED=false)
    # Why the authorisation does not cover this account (None = not authorised at all).
    live_authorization_problem: str | None = None

    def blocking_reason(self, environment: AccountEnvironment) -> str | None:
        """Why no new trade may open on an account of `environment`; None = allowed."""
        if self.platform_halted:
            return "trading is halted platform-wide by an administrator"
        if self.kill_switch_engaged:
            return "trading stopped"
        if not environment_permitted(self.mode, environment):
            return f"{environment.value} account not traded in {self.mode.value} mode"
        if environment is AccountEnvironment.LIVE and self.live_trading_locked:
            return "LIVE account but the LIVE hard lock is on"
        if environment is AccountEnvironment.LIVE and not self.live_authorized:
            return self.live_authorization_problem or NOT_AUTHORISED
        return None
