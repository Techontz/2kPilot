"""Authentication: users, login, server-side sessions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.config import Settings
from fxrobot.core.errors import AuthenticationError, ConflictError, RateLimitedError
from fxrobot.core.rate_limit import SlidingWindowRateLimiter
from fxrobot.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    tokens_match,
    validate_password_strength,
    verify_password,
)
from fxrobot.models import AuditOutcome, User, UserRole, UserSession
from fxrobot.services import audit
from fxrobot.services.context import RequestMeta

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Invalid email or password"
# Syntax check for operator-created accounts. Deliberately permits non-public
# domains (e.g. owner@2kfx.local) because installs are self-hosted.
_EMAIL_RE = re.compile(r"^[^@\s]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")
# Avoid a DB write on every request; refresh last_seen at most this often.
_LAST_SEEN_RESOLUTION = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: User
    session: UserSession
    session_token: str  # returned to the client once, stored only as a hash
    csrf_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_user(
    db: Session, *, email: str, password: str, display_name: str, role: UserRole
) -> User:
    problems = validate_password_strength(password)
    if problems:
        raise ValueError("Password " + ", ".join(problems))
    email = normalize_email(email)
    if len(email) > 320 or not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email address: {email!r}")
    if db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("A user with this email already exists")
    user = User(
        email=email, display_name=display_name, password_hash=hash_password(password), role=role
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.created",
        outcome=AuditOutcome.SUCCESS,
        actor=None,
        meta=RequestMeta.system(),
        target_type="user",
        target_id=str(user.id),
        details={"email": email, "role": role.value},
    )
    return user


def login(
    db: Session,
    *,
    email: str,
    password: str,
    meta: RequestMeta,
    settings: Settings,
    limiter: SlidingWindowRateLimiter,
) -> IssuedSession:
    email = normalize_email(email)
    keys = [f"email:{email}", f"ip:{meta.ip_address or 'unknown'}"]
    retry_after = max(limiter.retry_after(k) for k in keys)
    if retry_after:
        audit.record(
            db,
            action="auth.login.rate_limited",
            outcome=AuditOutcome.DENIED,
            actor=None,
            actor_label=email,
            meta=meta,
        )
        db.commit()
        raise RateLimitedError(
            "Too many login attempts. Try again later.", retry_after_seconds=retry_after
        )

    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(user.password_hash if user else None, password)
    if user is None or not password_ok or not user.is_active:
        for key in keys:
            limiter.hit(key)
        audit.record(
            db,
            action="auth.login.failed",
            outcome=AuditOutcome.FAILURE,
            actor=user,
            actor_label=email,
            meta=meta,
            details={"reason": "inactive" if user and password_ok else "bad_credentials"},
        )
        db.commit()
        raise AuthenticationError(INVALID_CREDENTIALS, code="invalid_credentials")

    limiter.reset(f"email:{email}")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    now = utcnow()
    session_token, csrf_token = generate_token(), generate_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.session_ttl_minutes),
        ip_address=meta.ip_address,
        user_agent=(meta.user_agent or "")[:512] or None,
    )
    user.last_login_at = now
    db.add(session)
    audit.record(
        db, action="auth.login.succeeded", outcome=AuditOutcome.SUCCESS, actor=user, meta=meta
    )
    db.commit()
    return IssuedSession(user, session, session_token, csrf_token)


def resolve_session(db: Session, token: str, settings: Settings) -> UserSession:
    """Return the live session for `token` or raise AuthenticationError."""
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = utcnow()
    if session is None or session.revoked_at is not None:
        raise AuthenticationError("Not authenticated")
    idle_limit = session.last_seen_at + timedelta(minutes=settings.session_idle_timeout_minutes)
    if now >= session.expires_at or now >= idle_limit:
        session.revoked_at = now
        db.commit()
        raise AuthenticationError("Session expired", code="session_expired")
    if not session.user.is_active:
        raise AuthenticationError("Not authenticated")
    if now - session.last_seen_at >= _LAST_SEEN_RESOLUTION:
        session.last_seen_at = now
        db.commit()
    return session


def csrf_valid(session: UserSession, csrf_token: str | None) -> bool:
    return bool(csrf_token) and tokens_match(csrf_token or "", session.csrf_token_hash)


def logout(db: Session, session: UserSession, meta: RequestMeta) -> None:
    session.revoked_at = utcnow()
    audit.record(
        db, action="auth.logout", outcome=AuditOutcome.SUCCESS, actor=session.user, meta=meta
    )
    db.commit()


def reverify_password(user: User, password: str | None) -> bool:
    """Step-up check for dangerous actions (e.g. enabling LIVE)."""
    return bool(password) and verify_password(user.password_hash, password or "")
