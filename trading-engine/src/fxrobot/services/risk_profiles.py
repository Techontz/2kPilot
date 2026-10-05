"""Turn a stored risk profile (managed in Laravel) into engine RiskLimits."""

from __future__ import annotations

from fxrobot.models import RiskProfile
from fxrobot.risk_engine.limits import RiskLimits

FIELDS = [
    "risk_per_trade_pct",
    "max_position_lots",
    "max_open_positions",
    "max_positions_per_symbol",
    "max_symbol_exposure_lots",
    "max_total_exposure_lots",
    "max_total_risk_pct",
    "max_daily_loss_pct",
    "max_weekly_loss_pct",
    "max_drawdown_pct",
    "max_trades_per_day",
    "max_spread_pips",
    "max_slippage_pips",
    "min_stop_pips",
    "max_stop_pips",
    "min_reward_risk",
    "allowed_sessions",
    "trading_hours_start",
    "trading_hours_end",
    "cooldown_after_losses",
    "cooldown_minutes",
    "max_data_age_seconds",
]


def limits_of(profile: RiskProfile) -> RiskLimits:
    return RiskLimits.from_mapping({f: getattr(profile, f) for f in FIELDS})
