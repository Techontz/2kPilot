"""Import historical candles from CSV.

Supported layouts (auto-detected from the header):

* MetaTrader 5 export ("History Center" / `Export Bars`), tab- or comma-separated:
  `<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>`
  with dates like `2024.01.02` and times like `13:00:00`.
* Generic: `time,open,high,low,close[,volume][,spread]` where `time` is ISO-8601
  or `YYYY-MM-DD HH:MM[:SS]`.

MT5 exports are in the broker's SERVER time; pass `utc_offset_hours` (for
example 2 or 3) so timestamps are converted to UTC. Generic files are taken as
UTC unless they carry an explicit offset.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fxrobot.domain.market import Candle
from fxrobot.market_data.validation import clean_candles

MAX_ROWS = 2_000_000


class CsvFormatError(ValueError):
    pass


@dataclass
class CsvImportResult:
    candles: list[Candle]
    rows_read: int
    dropped: list[str] = field(default_factory=list)
    detected_format: str = ""


def _parse_time(text: str, date_part: str | None = None) -> tuple[datetime, bool]:
    """Returns (UTC time, whether the text carried an explicit timezone)."""
    raw = f"{date_part} {text}" if date_part else text
    raw = raw.strip().replace(".", "-") if date_part else raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC), False
        except ValueError:
            continue
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CsvFormatError(f"unrecognised timestamp {raw!r}") from exc
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC), False
    return moment.astimezone(UTC), True


def parse_csv(content: str, *, utc_offset_hours: float = 0.0) -> CsvImportResult:
    sample = content[:4096]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    try:
        header = [h.strip().strip("<>").lower() for h in next(reader)]
    except StopIteration as exc:
        raise CsvFormatError("empty file") from exc
    mt5 = "date" in header and "time" in header
    needed = ["open", "high", "low", "close"]
    if not all(n in header for n in needed) or not (mt5 or "time" in header):
        raise CsvFormatError(
            "expected columns time/open/high/low/close (or MT5 <DATE> <TIME> <OPEN> …)"
        )
    idx = {name: header.index(name) for name in header}
    vol_col = next((c for c in ("tickvol", "volume", "tick_volume", "vol") if c in idx), None)
    offset = timedelta(hours=utc_offset_hours)
    candles: list[Candle] = []
    dropped: list[str] = []
    rows = 0
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        rows += 1
        if rows > MAX_ROWS:
            raise CsvFormatError(f"file exceeds {MAX_ROWS} rows")
        try:
            if mt5:
                moment, explicit = _parse_time(row[idx["time"]], row[idx["date"]])
            else:
                moment, explicit = _parse_time(row[idx["time"]])
            candle = Candle(
                # The offset only applies to naive (server-time) stamps.
                time=moment if explicit else moment - offset,
                open=Decimal(row[idx["open"]]),
                high=Decimal(row[idx["high"]]),
                low=Decimal(row[idx["low"]]),
                close=Decimal(row[idx["close"]]),
                tick_volume=int(float(row[idx[vol_col]])) if vol_col else 0,
                spread_points=int(float(row[idx["spread"]])) if "spread" in idx else None,
            )
            if not all(p.is_finite() for p in (candle.open, candle.high, candle.low, candle.close)):
                raise CsvFormatError("non-finite price")
        except (IndexError, InvalidOperation, ValueError, OverflowError, CsvFormatError) as exc:
            dropped.append(f"line {line_no}: {exc}")
            continue
        candles.append(candle)
    cleaned, invalid = clean_candles(candles)
    return CsvImportResult(
        candles=cleaned,
        rows_read=rows,
        dropped=dropped + invalid,
        detected_format="mt5" if mt5 else "generic",
    )
