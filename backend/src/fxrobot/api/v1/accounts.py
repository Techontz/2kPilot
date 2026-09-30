from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep, SettingsDep
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.core.errors import AppError, NotFoundError
from fxrobot.domain.trading import AssignmentStatus, TradeStatus
from fxrobot.models import (
    BrokerConnection,
    BrokerSymbol,
    RiskProfile,
    StrategyAssignment,
    Trade,
    TradingAccount,
)
from fxrobot.services import brokers as svc
from fxrobot.services import readiness

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountPatch(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    trading_enabled: bool | None = None
    risk_profile_id: uuid.UUID | None = None
    clear_risk_profile: bool = False


def _detail(db: DbDep, manager: ManagerDep, a: TradingAccount) -> dict[str, Any]:
    connection = db.get(BrokerConnection, a.connection_id)
    open_trades = (
        db.scalar(
            select(func.count()).where(Trade.account_id == a.id, Trade.status == TradeStatus.OPEN)
        )
        or 0
    )
    strategies = (
        db.scalar(
            select(func.count()).where(
                StrategyAssignment.account_id == a.id,
                StrategyAssignment.status == AssignmentStatus.ENABLED,
            )
        )
        or 0
    )
    profile = db.get(RiskProfile, a.risk_profile_id) if a.risk_profile_id else None
    live = manager.status(a.connection_id).value if manager.peek(a.connection_id) else None
    return ser.account(
        a,
        connection=ser.connection(connection, live) if connection else None,
        open_positions=open_trades,
        active_strategies=strategies,
        risk_profile_name=profile.name if profile else None,
    )


@router.get("")
def list_accounts(_: CurrentUserDep, db: DbDep, manager: ManagerDep) -> list[dict[str, Any]]:
    return [_detail(db, manager, a) for a in svc.list_accounts(db)]


@router.get("/{account_id}")
def get_account(
    account_id: uuid.UUID, _: CurrentUserDep, db: DbDep, manager: ManagerDep
) -> dict[str, Any]:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    return _detail(db, manager, account)


@router.patch("/{account_id}")
def update_account(
    account_id: uuid.UUID,
    body: AccountPatch,
    owner: OwnerDep,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    manager: ManagerDep,
) -> dict[str, Any]:
    account = svc.update_account(
        db,
        account_id,
        actor=owner,
        meta=meta,
        settings=settings,
        label=body.label,
        trading_enabled=body.trading_enabled,
        risk_profile_id=body.risk_profile_id,
        clear_risk_profile=body.clear_risk_profile,
    )
    return _detail(db, manager, account)


@router.post("/{account_id}/sync")
def sync_account(
    account_id: uuid.UUID, _: OwnerDep, db: DbDep, manager: ManagerDep
) -> dict[str, Any]:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    try:
        adapter = manager.get(account.connection_id)
        svc.sync_account(db, account, adapter, snapshot=True)
        svc.sync_symbols(db, account.connection, adapter)
    except BrokerError as exc:
        raise AppError(f"Broker unavailable: {exc}", code="broker_unavailable") from exc
    return _detail(db, manager, account)


@router.get("/{account_id}/symbols")
def symbols(account_id: uuid.UUID, _: CurrentUserDep, db: DbDep) -> list[dict[str, Any]]:
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    rows = db.scalars(
        select(BrokerSymbol)
        .where(BrokerSymbol.connection_id == account.connection_id)
        .order_by(BrokerSymbol.name)
    )
    return [
        {
            "name": s.name,
            "canonical": s.canonical,
            "description": s.description,
            "digits": s.digits,
            "point": ser.d(s.point),
            "contract_size": ser.d(s.contract_size),
            "volume_min": ser.d(s.volume_min),
            "volume_max": ser.d(s.volume_max),
            "volume_step": ser.d(s.volume_step),
            "trade_allowed": s.trade_allowed,
            "base_currency": s.base_currency,
            "quote_currency": s.quote_currency,
        }
        for s in rows
    ]


@router.get("/{account_id}/readiness")
def live_readiness(
    account_id: uuid.UUID, _: CurrentUserDep, db: DbDep, settings: SettingsDep, manager: ManagerDep
) -> dict[str, Any]:
    return readiness.checklist(db, account_id, settings, manager)
