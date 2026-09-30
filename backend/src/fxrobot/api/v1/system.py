from __future__ import annotations

from fastapi import APIRouter

from fxrobot import __version__
from fxrobot.api.deps import CurrentUserDep, DbDep, SettingsDep
from fxrobot.schemas.system import SystemStatusOut, TradingStatusOut
from fxrobot.services import trading_control

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusOut)
def system_status(_: CurrentUserDep, db: DbDep, settings: SettingsDep) -> SystemStatusOut:
    """Everything the Overview needs to answer 'is it running, and in which mode?'."""
    status = trading_control.get_status(db, settings)
    return SystemStatusOut(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.app_env.value,
        trading=TradingStatusOut.from_status(status),
        broker_accounts_connected=0,
    )
