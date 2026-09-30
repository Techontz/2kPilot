from __future__ import annotations

from fastapi import APIRouter

from fxrobot.api.deps import CurrentUserDep, DbDep, MetaDep, OwnerDep, SettingsDep
from fxrobot.schemas.system import (
    ResumeTradingRequest,
    SetModeRequest,
    StopTradingRequest,
    TradingStatusOut,
)
from fxrobot.services import trading_control

router = APIRouter(prefix="/trading", tags=["trading"])


def _status(db: DbDep, settings: SettingsDep) -> TradingStatusOut:
    return TradingStatusOut.from_status(trading_control.get_status(db, settings))


@router.get("/status", response_model=TradingStatusOut)
def trading_status(_: CurrentUserDep, db: DbDep, settings: SettingsDep) -> TradingStatusOut:
    return _status(db, settings)


@router.post("/stop", response_model=TradingStatusOut)
def stop_all_trading(
    body: StopTradingRequest, owner: OwnerDep, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> TradingStatusOut:
    """KILL SWITCH: block new orders and automated execution. Open positions are untouched."""
    trading_control.engage_kill_switch(db, actor=owner, reason=body.reason, meta=meta)
    return _status(db, settings)


@router.post("/resume", response_model=TradingStatusOut)
def resume_trading(
    _: ResumeTradingRequest, owner: OwnerDep, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> TradingStatusOut:
    trading_control.release_kill_switch(db, actor=owner, meta=meta)
    return _status(db, settings)


@router.put("/mode", response_model=TradingStatusOut)
def set_trading_mode(
    body: SetModeRequest, owner: OwnerDep, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> TradingStatusOut:
    trading_control.set_mode(
        db,
        actor=owner,
        mode=body.mode,
        settings=settings,
        meta=meta,
        password=body.password,
        confirmation_phrase=body.confirmation_phrase,
    )
    return _status(db, settings)
