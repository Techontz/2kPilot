"""Risk limits. `None` disables an optional limit; mandatory rules cannot be disabled.

Pip and lot limits apply to SPOT trades (Paper). Contract trades (Rise/Fall,
Multipliers) are sized by `stake_amount` — the most one contract can lose —
and bounded by the money limits (stake cap, daily loss amount, losing streak,
daily profit target), which apply to every trade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from decimal import Decimal
from typing import Any

# Limits that can never be switched off (None is refused rather than crashing later).
MANDATORY = frozenset(
    {"risk_per_trade_pct", "allowed_sessions", "max_data_age_seconds", "stake_amount"}
)
MONEY_FIELDS = frozenset(
    {
        "stake_amount",
        "max_stake_amount",
        "max_daily_loss_amount",
        "daily_profit_target_amount",
        "min_account_balance",
    }
)
# Limits where a SMALLER value is stricter (strategy caps take the minimum).
_TIGHTER_IS_SMALLER = frozenset(
    {
        "risk_per_trade_pct",
        "max_daily_loss_pct",
        "max_weekly_loss_pct",
        "max_drawdown_pct",
        "max_open_positions",
        "max_positions_per_symbol",
        "max_trades_per_day",
        "max_total_risk_pct",
    }
)


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: Decimal = Decimal("0.5")
    max_position_lots: Decimal | None = Decimal("1.0")
    max_open_positions: int | None = 3
    max_positions_per_symbol: int | None = 1
    max_symbol_exposure_lots: Decimal | None = Decimal("1.0")
    max_total_exposure_lots: Decimal | None = Decimal("3.0")
    max_total_risk_pct: Decimal | None = Decimal("2.0")
    max_daily_loss_pct: Decimal | None = Decimal("2.0")
    max_weekly_loss_pct: Decimal | None = Decimal("4.0")
    max_drawdown_pct: Decimal | None = Decimal("10.0")
    max_trades_per_day: int | None = 20
    max_spread_pips: Decimal | None = Decimal("2.5")
    max_slippage_pips: Decimal | None = Decimal("1.5")
    min_stop_pips: Decimal | None = Decimal("8")
    max_stop_pips: Decimal | None = Decimal("150")
    min_reward_risk: Decimal | None = Decimal("1.5")
    allowed_sessions: tuple[str, ...] = ("LONDON", "OVERLAP", "NEW_YORK")
    # Optional UTC window "HH:MM"–"HH:MM" (may wrap past midnight). Both or neither.
    trading_hours_start: str | None = None
    trading_hours_end: str | None = None
    cooldown_after_losses: int | None = 3
    cooldown_minutes: int | None = 240
    max_data_age_seconds: int = 120
    # ── stake-based limits (account currency) ──
    stake_amount: Decimal = Decimal("1.00")  # fixed stake per contract
    max_stake_amount: Decimal | None = Decimal("5.00")
    max_daily_loss_amount: Decimal | None = None  # money, in addition to max_daily_loss_pct
    max_consecutive_losses: int | None = 3  # halt new trades for the rest of the UTC day
    daily_profit_target_amount: Decimal | None = None  # stop for the day once reached
    # No new trades while the account balance is below this (account currency).
    min_account_balance: Decimal | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> RiskLimits:
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            if raw is None:
                if f.name in MANDATORY:
                    raise ValueError(f"{f.name} is mandatory and cannot be disabled")
                values[f.name] = None
            elif f.name in ("trading_hours_start", "trading_hours_end"):
                values[f.name] = str(raw).strip()[:5] or None
            elif f.name == "allowed_sessions":
                if isinstance(raw, str) or not isinstance(raw, list | tuple):
                    raise ValueError("allowed_sessions must be a list of session names")
                values[f.name] = tuple(str(s).upper() for s in raw)
            elif (
                f.name in ("risk_per_trade_pct",)
                or f.name in MONEY_FIELDS
                or "pct" in f.name
                or "pips" in f.name
                or "lots" in f.name
                or f.name == "min_reward_risk"
            ):
                values[f.name] = Decimal(str(raw))
            else:
                values[f.name] = int(raw)
        limits = cls(**values)
        limits.validate()
        return limits

    def validate(self) -> None:
        if not Decimal("0.01") <= self.risk_per_trade_pct <= Decimal(5):
            raise ValueError("risk_per_trade_pct must be between 0.01 and 5")
        for name in (
            "max_daily_loss_pct",
            "max_weekly_loss_pct",
            "max_drawdown_pct",
            "max_total_risk_pct",
        ):
            value = getattr(self, name)
            if value is not None and not Decimal(0) < value <= Decimal(100):
                raise ValueError(f"{name} must be between 0 and 100")
        if (
            self.min_stop_pips is not None
            and self.max_stop_pips is not None
            and self.min_stop_pips > self.max_stop_pips
        ):
            raise ValueError("min_stop_pips cannot exceed max_stop_pips")
        if self.max_data_age_seconds < 1:
            raise ValueError("max_data_age_seconds must be positive")
        if (self.trading_hours_start is None) != (self.trading_hours_end is None):
            raise ValueError("set both trading_hours_start and trading_hours_end, or neither")
        for name in ("trading_hours_start", "trading_hours_end"):
            value = getattr(self, name)
            if value is not None and parse_hhmm(value) is None:
                raise ValueError(f"{name} must be HH:MM (UTC)")
        if not Decimal(0) < self.stake_amount <= Decimal(100_000):
            raise ValueError("stake_amount must be between 0 and 100000")
        if self.max_stake_amount is not None and self.stake_amount > self.max_stake_amount:
            raise ValueError("stake_amount cannot exceed max_stake_amount")
        for name in (
            "max_stake_amount",
            "max_daily_loss_amount",
            "daily_profit_target_amount",
            "min_account_balance",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_consecutive_losses is not None and self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be at least 1")
        valid = {"ASIA", "LONDON", "OVERLAP", "NEW_YORK"}
        if not set(self.allowed_sessions) <= valid:
            raise ValueError(f"allowed_sessions must be within {sorted(valid)}")

    def tightened(self, caps: dict[str, Any]) -> RiskLimits:
        """These limits with a strategy's caps applied: a cap only ever makes a limit
        STRICTER (the smaller value wins; a disabled limit takes the cap). Unknown
        or loosening caps are ignored."""
        changes: dict[str, Any] = {}
        for name, cap in caps.items():
            if name not in _TIGHTER_IS_SMALLER or cap is None:
                continue
            current = getattr(self, name)
            value: Decimal | int = Decimal(str(cap)) if "pct" in name else int(cap)
            if current is None or value < current:
                changes[name] = value
        if not changes:
            return self
        limits = replace(self, **changes)
        limits.validate()
        return limits

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            out[key] = (
                format(value.normalize(), "f")  # "0.5", not the DB's "0.500"
                if isinstance(value, Decimal)
                else (list(value) if isinstance(value, tuple) else value)
            )
        return out


def parse_hhmm(value: str) -> int | None:
    """Minutes after midnight for "HH:MM", or None if malformed."""
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 2 for p in parts):
        return None
    hours, minutes = int(parts[0]), int(parts[1])
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


DEFAULT_LIMITS = RiskLimits()
