from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from fxrobot import __version__
from fxrobot.api.deps import CurrentUserDep, SettingsDep

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def settings_view(_: CurrentUserDep, settings: SettingsDep) -> dict[str, Any]:
    """Read-only operator settings (secrets are reported as present/absent only)."""
    return {
        "version": __version__,
        "environment": settings.app_env.value,
        "live_trading_enabled": settings.live_trading_enabled,
        "engine_enabled": settings.engine_enabled,
        "engine_tick_seconds": settings.engine_tick_seconds,
        "encryption_key_configured": bool(settings.secret_encryption_key.get_secret_value()),
        "cookie_secure": settings.cookie_secure,
        "session_ttl_minutes": settings.session_ttl_minutes,
        "session_idle_timeout_minutes": settings.session_idle_timeout_minutes,
        "database": settings.database_url.split("@")[-1].split("?")[0],
    }
