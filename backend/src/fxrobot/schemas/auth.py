from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fxrobot.models import UserRole


class LoginRequest(BaseModel):
    # Not EmailStr: login must not reveal format rules, and self-hosted
    # installs may use non-public domains (e.g. owner@2kfx.local).
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    last_login_at: datetime | None


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime
