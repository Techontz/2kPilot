"""Risk limits. `None` disables an optional limit; mandatory rules cannot be disabled."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from typing import Any

# Limits that can never be switched off (None is refused rather than crashing later).
MANDATORY = frozenset({"risk_per_trade_pct", "allowed_sessions", "max_data_age_seconds"})


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
    max_trades_per_day: int | None = 5
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
        valid = {"ASIA", "LONDON", "OVERLAP", "NEW_YORK"}
        if not set(self.allowed_sessions) <= valid:
            raise ValueError(f"allowed_sessions must be within {sorted(valid)}")

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
