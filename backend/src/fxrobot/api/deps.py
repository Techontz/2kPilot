"""FastAPI dependencies: settings, DB sessions, authentication, CSRF."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from fxrobot.backtesting.service import BacktestService
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.config import Settings
from fxrobot.core.errors import AuthenticationError, PermissionDeniedError
from fxrobot.models import User, UserRole, UserSession
from fxrobot.services import auth as auth_service
from fxrobot.services.context import RequestMeta

SESSION_COOKIE = "fx_session"
CSRF_COOKIE = "fx_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


def _client_ip(request: Request, trusted_proxies: list[str]) -> str | None:
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if peer in trusted_proxies and forwarded:
        candidate = forwarded.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return peer
    return peer


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_request_meta(request: Request, settings: SettingsDep) -> RequestMeta:
    return RequestMeta(
        ip_address=_client_ip(request, settings.trusted_proxies),
        user_agent=request.headers.get("user-agent"),
    )


DbDep = Annotated[Session, Depends(get_db)]
MetaDep = Annotated[RequestMeta, Depends(get_request_meta)]


def get_current_session(request: Request, db: DbDep, settings: SettingsDep) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthenticationError("Not authenticated")
    session = auth_service.resolve_session(db, token, settings)
    if request.method not in SAFE_METHODS and not auth_service.csrf_valid(
        session, request.headers.get(CSRF_HEADER)
    ):
        raise PermissionDeniedError("Missing or invalid CSRF token", code="csrf_failed")
    return session


CurrentSessionDep = Annotated[UserSession, Depends(get_current_session)]


def get_current_user(session: CurrentSessionDep) -> User:
    return session.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_owner(user: CurrentUserDep) -> User:
    if user.role is not UserRole.OWNER:
        raise PermissionDeniedError("This action requires the owner role")
    return user


OwnerDep = Annotated[User, Depends(require_owner)]


def get_manager(request: Request) -> BrokerManager:
    manager: BrokerManager = request.app.state.broker_manager
    return manager


def get_backtests(request: Request) -> BacktestService:
    service: BacktestService = request.app.state.backtests
    return service


ManagerDep = Annotated[BrokerManager, Depends(get_manager)]
BacktestsDep = Annotated[BacktestService, Depends(get_backtests)]
