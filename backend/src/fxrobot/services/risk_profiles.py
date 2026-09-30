"""Risk profiles (account-specific limits)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.errors import AppError, ConflictError, NotFoundError
from fxrobot.models import AuditOutcome, RiskProfile, TradingAccount, User
from fxrobot.risk_engine.limits import DEFAULT_LIMITS, RiskLimits
from fxrobot.services import audit
from fxrobot.services.context import RequestMeta

DEFAULT_PROFILE_NAME = "Conservative (default)"
FIELDS = [
    "risk_per_trade_pct",
    "max_position_lots",
    "max_open_positions",
    "max_positions_per_symbol",
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
    "cooldown_after_losses",
    "cooldown_minutes",
    "max_data_age_seconds",
]


class RiskProfileError(AppError):
    code = "invalid_risk_profile"


def limits_of(profile: RiskProfile) -> RiskLimits:
    return RiskLimits.from_mapping({f: getattr(profile, f) for f in FIELDS})


def _apply(profile: RiskProfile, values: dict[str, Any]) -> None:
    merged = {f: getattr(profile, f, None) for f in FIELDS}
    merged.update({k: v for k, v in values.items() if k in FIELDS})
    try:
        limits = RiskLimits.from_mapping(merged)
    except (ValueError, ArithmeticError) as exc:
        raise RiskProfileError(str(exc)) from exc
    for f in FIELDS:
        value = getattr(limits, f)
        setattr(profile, f, list(value) if isinstance(value, tuple) else value)


def ensure_default_profile(db: Session) -> RiskProfile:
    profile = db.scalar(select(RiskProfile).where(RiskProfile.name == DEFAULT_PROFILE_NAME))
    if profile is None:
        profile = RiskProfile(name=DEFAULT_PROFILE_NAME, risk_per_trade_pct=Decimal("0.5"))
        _apply(profile, DEFAULT_LIMITS.as_json())
        db.add(profile)
        db.commit()
    return profile


def create_profile(
    db: Session, name: str, values: dict[str, Any], *, actor: User, meta: RequestMeta
) -> RiskProfile:
    name = name.strip()
    if not name:
        raise RiskProfileError("Name is required")
    if db.scalar(select(RiskProfile.id).where(RiskProfile.name == name)):
        raise ConflictError("A risk profile with this name already exists")
    profile = RiskProfile(name=name[:120], risk_per_trade_pct=Decimal("0.5"))
    _apply(profile, {**DEFAULT_LIMITS.as_json(), **values})
    db.add(profile)
    db.flush()
    audit.record(
        db,
        action="risk.profile_created",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="risk_profile",
        target_id=str(profile.id),
        details=limits_of(profile).as_json(),
    )
    db.commit()
    return profile


def update_profile(
    db: Session,
    profile_id: uuid.UUID,
    values: dict[str, Any],
    *,
    actor: User,
    meta: RequestMeta,
    name: str | None = None,
) -> RiskProfile:
    profile = db.get(RiskProfile, profile_id)
    if profile is None:
        raise NotFoundError("Risk profile not found")
    before = limits_of(profile).as_json()
    if name is not None:
        name = name.strip()[:120]
        if not name:
            raise RiskProfileError("Name is required")
        clash = db.scalar(
            select(RiskProfile.id).where(RiskProfile.name == name, RiskProfile.id != profile.id)
        )
        if clash is not None:
            raise ConflictError("A risk profile with this name already exists")
    _apply(profile, values)
    if name:
        profile.name = name
    after = limits_of(profile).as_json()
    audit.record(
        db,
        action="risk.settings_changed",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="risk_profile",
        target_id=str(profile.id),
        details={"changes": {k: [before[k], after[k]] for k in after if before[k] != after[k]}},
    )
    db.commit()
    return profile


def delete_profile(db: Session, profile_id: uuid.UUID, *, actor: User, meta: RequestMeta) -> None:
    profile = db.get(RiskProfile, profile_id)
    if profile is None:
        raise NotFoundError("Risk profile not found")
    if db.scalar(select(TradingAccount.id).where(TradingAccount.risk_profile_id == profile_id)):
        raise ConflictError("This profile is assigned to an account")
    audit.record(
        db,
        action="risk.profile_deleted",
        outcome=AuditOutcome.SUCCESS,
        actor=actor,
        meta=meta,
        target_type="risk_profile",
        target_id=str(profile_id),
        details={"name": profile.name},
    )
    db.delete(profile)
    db.commit()
