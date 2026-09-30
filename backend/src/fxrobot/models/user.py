from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import NOW_DEFAULT, str_enum, utcnow


class UserRole(StrEnum):
    OWNER = "owner"  # full control, including trading and live activation
    VIEWER = "viewer"  # read-only dashboards


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Binary comparison: the default collation is case-insensitive.
        CheckConstraint(
            "CAST(email AS BINARY) = CAST(LOWER(email) AS BINARY)", name="email_lowercase"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role", 16))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    last_login_at: Mapped[datetime | None]

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSession(Base):
    """A server-side login session. Only token hashes are stored."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id_active", "user_id", "revoked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="sessions")
