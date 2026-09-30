from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """Who/where an action came from, for audit records."""

    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def system(cls) -> RequestMeta:
        return cls(ip_address=None, user_agent="system")
