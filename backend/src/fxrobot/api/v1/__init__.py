from fastapi import APIRouter

from fxrobot.api.v1 import audit, auth, brokers, health, system, trading

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(system.router)
api_router.include_router(trading.router)
api_router.include_router(brokers.router)
api_router.include_router(audit.router)
