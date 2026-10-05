"""Read-only view of Laravel's `users` table.

Users, passwords, MFA and sessions are managed by the Laravel backend. The
engine only needs user ids for foreign keys (e.g. who created a version).
"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
