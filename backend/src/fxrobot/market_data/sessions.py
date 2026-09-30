"""Forex trading sessions (UTC, DST ignored — documented approximation).

Labels are used by the risk engine (allowed sessions) and analytics
(performance by session):

    ASIA      21:00–07:00  Sydney/Tokyo
    LONDON    07:00–12:00
    OVERLAP   12:00–16:00  London + New York (usually the most liquid)
    NEW_YORK  16:00–21:00
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum


class Session(StrEnum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    OVERLAP = "OVERLAP"
    NEW_YORK = "NEW_YORK"


def session_at(moment: datetime) -> Session:
    hour = moment.hour
    if 7 <= hour < 12:
        return Session.LONDON
    if 12 <= hour < 16:
        return Session.OVERLAP
    if 16 <= hour < 21:
        return Session.NEW_YORK
    return Session.ASIA


def is_fx_market_open(moment: datetime) -> bool:
    """Retail FX trades from Sunday ~21:00 UTC to Friday ~21:00 UTC.

    Brokers differ by an hour or so; a real broker's own trade-session
    information (market_closed errors) always takes precedence.
    """
    weekday = moment.weekday()  # Monday=0 … Sunday=6
    if weekday == 5:  # Saturday
        return False
    if weekday == 4 and moment.hour >= 21:  # Friday after close
        return False
    return not (weekday == 6 and moment.hour < 21)  # Sunday before open
