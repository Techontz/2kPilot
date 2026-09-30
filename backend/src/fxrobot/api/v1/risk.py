from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep, SettingsDep
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.core.errors import NotFoundError
from fxrobot.domain.trading import SignalStatus
from fxrobot.models import RiskProfile, Signal, SystemState, TradingAccount
from fxrobot.services import risk_profiles as svc
from fxrobot.trading_engine.context import build_risk_context

router = APIRouter(prefix="/risk", tags=["risk"])


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    limits: dict[str, Any]


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    limits: dict[str, Any] = Field(default_factory=dict)


def _profile(p: RiskProfile) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "limits": svc.limits_of(p).as_json(),
        "updated_at": ser.t(p.updated_at),
    }


@router.get("/profiles")
def profiles(_: CurrentUserDep, db: DbDep) -> list[dict[str, Any]]:
    return [_profile(p) for p in db.scalars(select(RiskProfile).order_by(RiskProfile.name))]


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create(body: ProfileBody, owner: OwnerDep, db: DbDep, meta: MetaDep) -> dict[str, Any]:
    return _profile(svc.create_profile(db, body.name, body.limits, actor=owner, meta=meta))


@router.put("/profiles/{profile_id}")
def update(
    profile_id: uuid.UUID, body: ProfilePatch, owner: OwnerDep, db: DbDep, meta: MetaDep
) -> dict[str, Any]:
    return _profile(
        svc.update_profile(db, profile_id, body.limits, actor=owner, meta=meta, name=body.name)
    )


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(profile_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep) -> None:
    svc.delete_profile(db, profile_id, actor=owner, meta=meta)


@router.get("/usage/{account_id}")
def usage(
    account_id: uuid.UUID, _: CurrentUserDep, db: DbDep, manager: ManagerDep, settings: SettingsDep
) -> dict[str, Any]:
    """How much of each limit is used right now — the Risk Management screen."""
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    profile = db.get(RiskProfile, account.risk_profile_id) if account.risk_profile_id else None
    violations = [
        ser.signal(s)
        for s in db.scalars(
            select(Signal)
            .where(Signal.account_id == account.id, Signal.status == SignalStatus.REJECTED)
            .order_by(Signal.created_at.desc())
            .limit(10)
        )
    ]
    base = {
        "account_id": str(account.id),
        "profile": _profile(profile) if profile else None,
        "recent_violations": violations,
        "live": False,
    }
    if profile is None:
        return base
    try:
        adapter = manager.get(account.connection_id)
        symbols = adapter.get_symbols()
        info = adapter.get_account()
    except BrokerError as exc:
        return base | {"error": f"Broker unavailable: {exc}"}
    state = db.get(SystemState, 1)
    if state is None:
        raise NotFoundError("System state missing")
    ctx = build_risk_context(
        db,
        account=account,
        adapter=adapter,
        state=state,
        live_locked=not settings.live_trading_enabled,
        symbol=symbols[0],
        account_info=info,
        broker_connected=adapter.is_connected,
    )
    limits = svc.limits_of(profile)

    def pct(num: Any, den: Any) -> float | None:
        return round(float(num / den * 100), 2) if den else None

    daily_loss = max(0, -(ctx.realized_pnl_today + ctx.unrealized_pnl))
    weekly_loss = max(0, -(ctx.realized_pnl_week + ctx.unrealized_pnl))
    dd = (ctx.peak_equity - ctx.equity) if ctx.peak_equity and ctx.equity is not None else 0
    open_risk = sum((p.risk_amount or 0 for p in ctx.open_positions), 0)
    return base | {
        "live": True,
        "equity": str(ctx.equity),
        "balance": str(ctx.balance),
        "currency": account.currency,
        "daily_loss": {
            "amount": str(daily_loss),
            "pct": pct(daily_loss, ctx.start_of_day_balance),
            "limit_pct": ser.d(limits.max_daily_loss_pct),
        },
        "weekly_loss": {
            "amount": str(weekly_loss),
            "pct": pct(weekly_loss, ctx.start_of_week_balance),
            "limit_pct": ser.d(limits.max_weekly_loss_pct),
        },
        "drawdown": {
            "amount": str(dd),
            "pct": pct(dd, ctx.peak_equity),
            "limit_pct": ser.d(limits.max_drawdown_pct),
            "peak_equity": str(ctx.peak_equity),
        },
        "open_risk": {
            "amount": str(open_risk),
            "pct": pct(open_risk, ctx.equity),
            "limit_pct": ser.d(limits.max_total_risk_pct),
            "unknown": any(p.risk_amount is None for p in ctx.open_positions),
        },
        "positions": {
            "open": len(ctx.open_positions),
            "max": limits.max_open_positions,
            "lots": str(sum((p.volume for p in ctx.open_positions), 0)),
            "max_lots": ser.d(limits.max_total_exposure_lots),
        },
        "trades_today": {"count": ctx.trades_today, "max": limits.max_trades_per_day},
        "consecutive_losses": {
            "count": ctx.consecutive_losses,
            "cooldown_after": limits.cooldown_after_losses,
        },
    }
