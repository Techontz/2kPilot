"""Time helpers and trade-server → UTC offset handling.

MT5 reports times in *trade-server time* encoded as if it were UTC. With
``BROKER_SERVER_UTC_OFFSET=auto`` the offset is measured as
``round((last_tick_time - utc_now) / 1800) * 1800`` on a liquid symbol while its
market is open, and re-measured hourly.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

HALF_HOUR = 1800
# A tick whose (time - now) is further than this from a half-hour multiple is stale.
MAX_TICK_LAG_SECONDS = 90
MAX_ABS_OFFSET = 14 * 3600

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]00:00)$")


def fmt_utc(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(int(epoch_seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp (``Z`` suffix). Raises ``ValueError``."""
    if not _ISO_RE.match(value):
        raise ValueError("timestamp must be ISO-8601 UTC, e.g. 2026-10-01T13:00:00Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def fx_market_probably_open(now_utc: float) -> bool:
    """Coarse FX weekly session: Sunday ~21:00 UTC to Friday ~22:00 UTC."""
    dt = datetime.fromtimestamp(now_utc, UTC)
    wd, hour = dt.weekday(), dt.hour  # Monday=0 .. Sunday=6
    if wd == 5:
        return False
    if wd == 4 and hour >= 21:
        return False
    return not (wd == 6 and hour < 22)


def offset_from_tick(tick_time: float, now_utc: float) -> int | None:
    """Derive the server offset from a *fresh* tick; ``None`` if the tick looks stale."""
    raw = tick_time - now_utc
    candidate = round(raw / HALF_HOUR) * HALF_HOUR
    if abs(raw - candidate) > MAX_TICK_LAG_SECONDS or abs(candidate) > MAX_ABS_OFFSET:
        return None
    return int(candidate)


class OffsetTracker:
    """Holds the current server UTC offset (fixed or auto-measured)."""

    def __init__(
        self,
        fixed_offset: int | None,
        refresh_seconds: float,
        clock: Callable[[], float],
        persist: Callable[[int, float], None] | None = None,
        initial: tuple[int, float] | None = None,
    ) -> None:
        self.fixed = fixed_offset
        self.refresh = refresh_seconds
        self.clock = clock
        self._persist = persist
        self.offset: int | None = fixed_offset
        self.measured_at: float | None = None
        if fixed_offset is None and initial is not None:
            self.offset, self.measured_at = initial

    @property
    def is_auto(self) -> bool:
        return self.fixed is None

    def needs_measurement(self) -> bool:
        if not self.is_auto:
            return False
        return self.measured_at is None or self.clock() - self.measured_at >= self.refresh

    def measure(self, session: Any, symbols: list[str]) -> int | None:
        """Runs on the MT5 worker thread. Updates and returns the offset if measurable."""
        now = self.clock()
        if not fx_market_probably_open(now):
            return None
        mt5 = session.mt5
        for name in _candidate_symbols(mt5, symbols):
            info = mt5.symbol_info(name)
            if info is None:
                continue
            if not info.visible:
                mt5.symbol_select(name, True)
            tick = mt5.symbol_info_tick(name)
            if tick is None or not tick.time:
                continue
            off = offset_from_tick(float(tick.time), self.clock())
            if off is not None:
                self.offset = off
                self.measured_at = self.clock()
                if self._persist is not None:
                    self._persist(off, self.measured_at)
                return off
        return None


def _candidate_symbols(mt5: Any, bases: list[str]) -> list[str]:
    out = list(bases)
    for base in bases:
        try:
            found = mt5.symbols_get(f"*{base}*") or ()
        except Exception:  # noqa: S112 - best effort discovery of suffixed names
            continue
        out.extend(s.name for s in found if s.name not in out)
    return out
