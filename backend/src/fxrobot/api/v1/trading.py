from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep, SettingsDep
from fxrobot.schemas.system import (
    ResumeTradingRequest,
    SetModeRequest,
    StopTradingRequest,
    TradingStatusOut,
)
from fxrobot.services import trading_control, trading_ops

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


class EmergencyBody(BaseModel):
    reason: str = Field(default="Emergency stop from dashboard", min_length=1, max_length=500)
    close_positions: bool = False


@router.post("/emergency-stop")
def emergency_stop(
    body: EmergencyBody,
    owner: OwnerDep,
    db: DbDep,
    meta: MetaDep,
    manager: ManagerDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Stop all trading and, only if explicitly requested, close every open position."""
    result = trading_ops.emergency_stop(
        db,
        manager=manager,
        actor=owner,
        meta=meta,
        close_positions=body.close_positions,
        reason=body.reason,
    )
    return {"result": result, "status": _status(db, settings).model_dump(mode="json")}
