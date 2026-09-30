from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from fxrobot.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    CurrentSessionDep,
    DbDep,
    MetaDep,
    SettingsDep,
)
from fxrobot.core.config import Settings
from fxrobot.schemas.auth import LoginRequest, SessionOut, UserOut
from fxrobot.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, settings: Settings, session_token: str, csrf: str) -> None:
    max_age = settings.session_ttl_minutes * 60
    common = {
        "max_age": max_age,
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, **common)  # type: ignore[arg-type]
    # Readable by the dashboard's JS so it can echo it in the X-CSRF-Token header.
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)  # type: ignore[arg-type]


def _clear_cookies(response: Response, settings: Settings) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")


@router.post("/login", response_model=SessionOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    meta: MetaDep,
) -> SessionOut:
    issued = auth_service.login(
        db,
        email=body.email,
        password=body.password,
        meta=meta,
        settings=settings,
        limiter=request.app.state.login_limiter,
    )
    _set_cookies(response, settings, issued.session_token, issued.csrf_token)
    return SessionOut(
        user=UserOut.model_validate(issued.user), expires_at=issued.session.expires_at
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: CurrentSessionDep, db: DbDep, settings: SettingsDep, meta: MetaDep) -> Response:
    auth_service.logout(db, session, meta)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(response, settings)
    return response


@router.get("/me", response_model=SessionOut)
def me(session: CurrentSessionDep) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(session.user), expires_at=session.expires_at)
