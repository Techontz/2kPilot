from fastapi import APIRouter

from fxrobot.api.v1 import (
    accounts,
    analytics,
    audit,
    auth,
    backtests,
    brokers,
    health,
    market,
    notifications,
    overview,
    risk,
    settings,
    strategies,
    stream,
    system,
    trading,
    trading_records,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    health,
    auth,
    system,
    trading,
    overview,
    brokers,
    accounts,
    market,
    strategies,
    risk,
    trading_records,
    analytics,
    backtests,
    notifications,
    settings,
    audit,
    stream,
):
    api_router.include_router(module.router)
