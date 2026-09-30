"""Market data: sessions, conversion, resampling, validation, CSV import,
synthetic generation and candle storage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from fxrobot.domain.market import Candle, Quote, SymbolInfo, Timeframe
from fxrobot.domain.trading import DataSource
from fxrobot.market_data.conversion import (
    conversion_rate,
    pip_value,
    point_value,
    price_to_pips,
    profit_in_account,
)
from fxrobot.market_data.csv_import import CsvFormatError, parse_csv
from fxrobot.market_data.resample import resample
from fxrobot.market_data.sessions import Session as FxSession
from fxrobot.market_data.sessions import is_fx_market_open, session_at
from fxrobot.market_data.store import (
    checksum,
    delete_dataset,
    get_or_create_dataset,
    load_candles,
    upsert_candles,
)
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries
from fxrobot.market_data.validation import clean_candles, is_stale, validate_candles
from fxrobot.models import Dataset

D = Decimal


def t(day: int, hour: int, minute: int = 0, month: int = 9) -> datetime:
    """A UTC moment in 2026. Sep 28 = Monday … Oct 2 = Friday, Oct 3/4 = weekend."""
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def bar(
    at: datetime,
    o: str = "1.10000",
    h: str = "1.10100",
    lo: str = "1.09900",
    c: str = "1.10050",
    vol: int = 10,
    spread: int | None = 12,
) -> Candle:
    return Candle(at, D(o), D(h), D(lo), D(c), vol, spread)


def series(start: datetime, tf: Timeframe, n: int) -> list[Candle]:
    return [bar(start + tf.delta * i) for i in range(n)]


# ── sessions ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 0, FxSession.ASIA),
        (6, 59, FxSession.ASIA),
        (7, 0, FxSession.LONDON),
        (11, 59, FxSession.LONDON),
        (12, 0, FxSession.OVERLAP),
        (15, 59, FxSession.OVERLAP),
        (16, 0, FxSession.NEW_YORK),
        (20, 59, FxSession.NEW_YORK),
        (21, 0, FxSession.ASIA),
        (23, 59, FxSession.ASIA),
    ],
)
def test_session_boundaries(hour: int, minute: int, expected: FxSession) -> None:
    assert session_at(t(30, hour, minute)) is expected


@pytest.mark.parametrize(
    ("moment", "is_open"),
    [
        (t(2, 20, 59, month=10), True),  # Friday just before close
        (t(2, 21, 0, month=10), False),  # Friday close
        (t(3, 0, 0, month=10), False),  # Saturday
        (t(3, 23, 59, month=10), False),
        (t(4, 20, 59, month=10), False),  # Sunday before open
        (t(4, 21, 0, month=10), True),  # Sunday open
        (t(28, 0, 0), True),  # Monday midnight
        (t(30, 12, 0), True),  # mid-week
    ],
)
def test_market_open_weekend_edges(moment: datetime, is_open: bool) -> None:
    assert is_fx_market_open(moment) is is_open


# ── conversion ──────────────────────────────────────────────────────────

NOW = t(30, 10)
QUOTES = {
    "EURUSD": Quote("EURUSD", D("1.1000"), D("1.1002"), NOW),  # mid 1.1001
    "USDJPY": Quote("USDJPY", D("150.00"), D("150.02"), NOW),  # mid 150.01
    "GBPUSD": Quote("GBPUSD", D("1.2500"), D("1.2500"), NOW),
    "USDCHF": Quote("USDCHF", D("0.8000"), D("0.8000"), NOW),
}


def lookup(symbol: str) -> Quote | None:
    return QUOTES.get(symbol)


def no_quotes(_: str) -> Quote | None:
    return None


EURUSD = SymbolInfo(
    "EURUSD", "", "EUR", "USD", 5, D("0.00001"), D(100000), D("0.01"), D(50), D("0.01"), True
)
USDJPY = SymbolInfo(
    "USDJPY", "", "USD", "JPY", 3, D("0.001"), D(100000), D("0.01"), D(50), D("0.01"), True
)


def test_conversion_same_currency_is_one() -> None:
    assert conversion_rate("USD", "USD", no_quotes) == D(1)


def test_conversion_direct_uses_mid() -> None:
    assert conversion_rate("EUR", "USD", lookup) == D("1.1001")


def test_conversion_inverse() -> None:
    assert conversion_rate("JPY", "USD", lookup) == D(1) / D("150.01")
    assert conversion_rate("USD", "EUR", lookup) == D(1) / D("1.1001")


def test_conversion_cross_via_usd() -> None:
    assert conversion_rate("EUR", "JPY", lookup) == D("1.1001") * D("150.01")
    assert conversion_rate("GBP", "CHF", lookup) == D("1.2500") * D("0.8000")
    assert conversion_rate("JPY", "GBP", lookup) == (D(1) / D("150.01")) * (D(1) / D("1.25"))


def test_conversion_unknown_returns_none() -> None:
    assert conversion_rate("EUR", "USD", no_quotes) is None
    assert conversion_rate("NZD", "USD", lookup) is None
    assert conversion_rate("EUR", "NZD", lookup) is None


def test_conversion_ignores_zero_price_quote() -> None:
    zero = {"EURUSD": Quote("EURUSD", D(0), D(0), NOW)}
    assert conversion_rate("EUR", "USD", zero.get) is None


def test_point_and_pip_value_usd_quote() -> None:
    assert point_value(EURUSD, "USD", no_quotes) == D("1.00000")
    assert pip_value(EURUSD, "USD", no_quotes) == D(10)
    assert EURUSD.pip_size == D("0.0001")


def test_point_and_pip_value_jpy_quote_in_usd() -> None:
    pv = point_value(USDJPY, "USD", lookup)
    assert pv == D(100000) * D("0.001") / D("150.01")
    assert pip_value(USDJPY, "USD", lookup) == pv * 10
    assert USDJPY.pip_size == D("0.01")


def test_point_value_prefers_broker_value() -> None:
    symbol = replace(EURUSD, point_value=D("0.9"))
    assert point_value(symbol, "GBP", no_quotes) == D("0.9")


def test_point_value_missing_conversion_is_none() -> None:
    assert point_value(USDJPY, "USD", no_quotes) is None
    assert pip_value(USDJPY, "USD", no_quotes) is None


def test_pip_size_for_four_digit_quote() -> None:
    four = replace(EURUSD, digits=4, point=D("0.0001"))
    assert four.pip_size == D("0.0001")


def test_price_to_pips_and_profit() -> None:
    assert price_to_pips(D("-0.0025"), EURUSD) == D(25)
    assert price_to_pips(D("0.25"), USDJPY) == D(25)
    profit = profit_in_account(EURUSD, 1, D("0.5"), D("1.1000"), D("1.1020"), "USD", no_quotes)
    assert profit == D("100.0000")
    loss = profit_in_account(EURUSD, -1, D("0.5"), D("1.1000"), D("1.1020"), "USD", no_quotes)
    assert loss == D("-100.0000")
    assert profit_in_account(USDJPY, 1, D(1), D(150), D(151), "USD", no_quotes) is None


# ── resampling ──────────────────────────────────────────────────────────


def test_resample_drops_incomplete_last_bucket() -> None:
    m15 = series(t(30, 9), Timeframe.M15, 8)  # 09:00 … 10:45
    out = resample(m15, Timeframe.H1)
    assert [c.time for c in out] == [t(30, 9)]


def test_resample_emits_last_bucket_only_when_closed_by_until() -> None:
    m15 = series(t(30, 9), Timeframe.M15, 8)
    assert len(resample(m15, Timeframe.H1, until=t(30, 10, 59))) == 1
    assert [c.time for c in resample(m15, Timeframe.H1, until=t(30, 11))] == [
        t(30, 9),
        t(30, 10),
    ]


def test_resample_partial_bucket_not_emitted_even_with_until() -> None:
    m15 = series(t(30, 9), Timeframe.M15, 6)  # 10:00 bucket only has 2 of 4 bars
    out = resample(m15, Timeframe.H1, until=t(30, 10, 30))
    assert [c.time for c in out] == [t(30, 9)]


def test_resample_merges_ohlcv() -> None:
    bars = [
        bar(t(30, 9, 0), "1.1000", "1.1010", "1.0990", "1.1005", 5, 10),
        bar(t(30, 9, 15), "1.1005", "1.1030", "1.1000", "1.1020", 6, 14),
        bar(t(30, 9, 30), "1.1020", "1.1025", "1.0980", "1.0990", 7, None),
        bar(t(30, 9, 45), "1.0990", "1.1000", "1.0985", "1.0995", 8, 11),
    ]
    (h1,) = resample(bars, Timeframe.H1, until=t(30, 10))
    assert h1 == Candle(t(30, 9), D("1.1000"), D("1.1030"), D("1.0980"), D("1.0995"), 26, 14)


def test_resample_spread_none_when_unknown() -> None:
    bars = [bar(t(30, 9, 15 * i), spread=None) for i in range(4)]
    (h1,) = resample(bars, Timeframe.H1, until=t(30, 10))
    assert h1.spread_points is None


def test_resample_h4_alignment() -> None:
    h1 = series(t(30, 2), Timeframe.H1, 7)  # 02:00 … 08:00
    out = resample(h1, Timeframe.H4, until=t(30, 9))
    # Buckets start at 00:00, 04:00 (08:00 is incomplete).
    assert [c.time for c in out] == [t(30, 0), t(30, 4)]
    assert out[0].tick_volume == 20  # only 02:00 and 03:00 exist
    assert out[1].tick_volume == 40


def test_resample_empty() -> None:
    assert resample([], Timeframe.H1, until=t(30, 10)) == []


def test_timeframe_floor() -> None:
    assert Timeframe.M15.floor(t(30, 10, 29)) == t(30, 10, 15)
    assert Timeframe.D1.floor(t(30, 23, 59)) == t(30, 0)
    assert Timeframe.H4.floor(t(30, 3, 59)) == t(30, 0)


# ── validation ──────────────────────────────────────────────────────────


def test_validate_clean_series() -> None:
    report = validate_candles(series(t(30, 9), Timeframe.M15, 10), Timeframe.M15)
    assert report.is_clean
    assert report.bar_count == 10
    assert report.gaps == []
    assert report.summary() == {
        "bars": 10,
        "invalid": 0,
        "duplicates": 0,
        "out_of_order": 0,
        "misaligned": 0,
        "gaps": 0,
        "missing_bars": 0,
        "spikes": 0,
    }


def test_validate_duplicates() -> None:
    bars = series(t(30, 9), Timeframe.M15, 3)
    report = validate_candles([*bars, bars[-1]], Timeframe.M15)
    assert report.duplicates == 1
    assert not report.is_clean


def test_validate_out_of_order() -> None:
    a, b, c = series(t(30, 9), Timeframe.M15, 3)
    report = validate_candles([a, c, b], Timeframe.M15)
    assert report.out_of_order == 1
    assert not report.is_clean


@pytest.mark.parametrize(
    ("candle", "problem"),
    [
        (bar(t(30, 9), o="0"), "non-positive price"),
        (bar(t(30, 9), h="1.10020"), "high/low do not contain open/close"),
        (bar(t(30, 9), lo="1.10010"), "high/low do not contain open/close"),
        (bar(t(30, 9), vol=-1), "negative volume"),
        (bar(datetime(2026, 9, 30, 9)), "naive timestamp"),
    ],
)
def test_validate_invalid_ohlc(candle: Candle, problem: str) -> None:
    report = validate_candles([candle], Timeframe.M15)
    assert len(report.invalid_bars) == 1
    assert report.invalid_bars[0].endswith(problem)
    assert not report.is_clean


def test_validate_misaligned() -> None:
    report = validate_candles([bar(t(30, 9)), bar(t(30, 9, 22))], Timeframe.M15)
    assert report.misaligned == 1
    assert not report.is_clean


def test_validate_gap_detected() -> None:
    report = validate_candles([bar(t(30, 10)), bar(t(30, 10, 45))], Timeframe.M15)
    assert len(report.gaps) == 1
    assert report.gaps[0].start == t(30, 10, 15)
    assert report.gaps[0].missing_bars == 2
    assert report.missing_bars == 2
    assert report.is_clean  # gaps are reported, not treated as corruption


def test_validate_weekend_is_not_a_gap() -> None:
    fri_last = t(2, 20, 45, month=10)
    sun_first = t(4, 21, 0, month=10)
    assert validate_candles([bar(fri_last), bar(sun_first)], Timeframe.M15).gaps == []
    h1 = validate_candles([bar(t(2, 20, month=10)), bar(t(4, 21, month=10))], Timeframe.H1)
    assert h1.gaps == []


def test_validate_gap_after_weekend_open_counted() -> None:
    report = validate_candles([bar(t(2, 20, month=10)), bar(t(4, 22, month=10))], Timeframe.H1)
    assert [(g.start, g.missing_bars) for g in report.gaps] == [(t(2, 21, month=10), 1)]


def test_validate_d1_gaps_count_weekdays_only() -> None:
    thu, fri, mon = t(1, 0, month=10), t(2, 0, month=10), t(5, 0, month=10)
    assert validate_candles([bar(fri), bar(mon)], Timeframe.D1).gaps == []
    report = validate_candles([bar(thu), bar(mon)], Timeframe.D1)
    assert report.missing_bars == 1
    assert report.gaps[0].start == fri


def test_validate_spikes() -> None:
    bars = series(t(30, 0), Timeframe.M15, 25)  # range 0.002 each
    spike_time = bars[12].time
    bars[12] = bar(spike_time, "1.10000", "1.13000", "1.09000", "1.10050")  # range 0.04
    report = validate_candles(bars, Timeframe.M15)
    assert report.spikes == [spike_time]
    assert report.summary()["spikes"] == 1


def test_validate_no_spike_check_under_20_bars() -> None:
    bars = series(t(30, 0), Timeframe.M15, 19)
    bars[5] = bar(bars[5].time, "1.10000", "1.13000", "1.09000", "1.10050")
    assert validate_candles(bars, Timeframe.M15).spikes == []


def test_clean_candles_sorts_dedupes_and_drops() -> None:
    a = bar(t(30, 9))
    b = bar(t(30, 9, 15))
    b2 = bar(t(30, 9, 15), c="1.10090")
    broken = bar(t(30, 9, 30), h="1.0")
    cleaned, dropped = clean_candles([b, broken, a, b2])
    assert cleaned == [a, b2]  # sorted, last duplicate wins
    assert dropped == [f"{t(30, 9, 30).isoformat()}: high/low do not contain open/close"]


def test_is_stale() -> None:
    assert is_stale(NOW - timedelta(seconds=61), NOW, 60)
    assert not is_stale(NOW - timedelta(seconds=60), NOW, 60)


# ── CSV import ──────────────────────────────────────────────────────────

MT5_HEADER = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"


def test_csv_mt5_tab_format() -> None:
    content = (
        MT5_HEADER
        + "2024.01.02\t13:00:00\t1.10000\t1.10200\t1.09900\t1.10100\t345\t0\t12\n"
        + "2024.01.02\t14:00\t1.10100\t1.10300\t1.10000\t1.10250\t200\t0\t9\n"
    )
    result = parse_csv(content)
    assert result.detected_format == "mt5"
    assert result.rows_read == 2
    assert result.dropped == []
    assert result.candles == [
        Candle(
            datetime(2024, 1, 2, 13, tzinfo=UTC),
            D("1.10000"),
            D("1.10200"),
            D("1.09900"),
            D("1.10100"),
            345,
            12,
        ),
        Candle(
            datetime(2024, 1, 2, 14, tzinfo=UTC),
            D("1.10100"),
            D("1.10300"),
            D("1.10000"),
            D("1.10250"),
            200,
            9,
        ),
    ]


def test_csv_mt5_utc_offset_converts_server_time() -> None:
    content = MT5_HEADER + "2024.01.02\t00:30:00\t1.1\t1.2\t1.0\t1.15\t1\t0\t1\n"
    result = parse_csv(content, utc_offset_hours=2)
    assert result.candles[0].time == datetime(2024, 1, 1, 22, 30, tzinfo=UTC)
    negative = parse_csv(content, utc_offset_hours=-1.5)
    assert negative.candles[0].time == datetime(2024, 1, 2, 2, 0, tzinfo=UTC)


def test_csv_generic_iso_comma() -> None:
    content = (
        "time,open,high,low,close,volume\n"
        "2024-01-02T13:00:00Z,1.1,1.2,1.0,1.15,50\n"
        "2024-01-02T16:00:00+02:00,1.15,1.25,1.1,1.2,60\n"
        "2024-01-02 15:00,1.2,1.3,1.1,1.25,70\n"
    )
    result = parse_csv(content)
    assert result.detected_format == "generic"
    assert [c.time for c in result.candles] == [
        datetime(2024, 1, 2, 13, tzinfo=UTC),
        datetime(2024, 1, 2, 14, tzinfo=UTC),  # +02:00 converted to UTC
        datetime(2024, 1, 2, 15, tzinfo=UTC),
    ]
    assert [c.tick_volume for c in result.candles] == [50, 60, 70]
    assert all(c.spread_points is None for c in result.candles)


def test_csv_generic_without_volume() -> None:
    result = parse_csv("time,open,high,low,close\n2024-01-02 13:00:00,1.1,1.2,1.0,1.15\n")
    assert result.candles[0].tick_volume == 0


def test_csv_malformed_rows_dropped_and_reported() -> None:
    content = (
        "time,open,high,low,close\n"
        "2024-01-02 13:00,1.1,1.2,1.0,1.15\n"
        "not-a-date,1.1,1.2,1.0,1.15\n"
        "2024-01-02 14:00,abc,1.2,1.0,1.15\n"
        "2024-01-02 15:00,1.1\n"
        "\n"
        "2024-01-02 16:00,1.1,1.0,1.2,1.15\n"  # high below low → dropped by validation
        "2024-01-02 17:00,1.1,1.2,1.0,1.15\n"
    )
    result = parse_csv(content)
    assert result.rows_read == 6  # blank line not counted
    assert [c.time.hour for c in result.candles] == [13, 17]
    assert len(result.dropped) == 4
    assert result.dropped[0].startswith("line 3: ")
    assert "not-a-date" in result.dropped[0]
    assert result.dropped[1].startswith("line 4: ")
    assert result.dropped[2].startswith("line 5: ")
    assert result.dropped[3].startswith("2024-01-02T16:00:00+00:00: ")


def test_csv_duplicates_deduplicated_and_sorted() -> None:
    content = (
        "time,open,high,low,close\n"
        "2024-01-02 14:00,1.1,1.2,1.0,1.15\n"
        "2024-01-02 13:00,1.1,1.2,1.0,1.15\n"
        "2024-01-02 14:00,1.1,1.2,1.0,1.18\n"
    )
    result = parse_csv(content)
    assert [c.time.hour for c in result.candles] == [13, 14]
    assert result.candles[1].close == D("1.18")


def test_csv_empty_file_errors() -> None:
    with pytest.raises(CsvFormatError, match="empty file"):
        parse_csv("")


@pytest.mark.parametrize(
    "header",
    [
        "open,high,low,close\n",  # no time
        "time,open,high,close\n",  # no low
        "<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\n",  # MT5 without <TIME>
        "foo,bar\n",
    ],
)
def test_csv_invalid_header_errors(header: str) -> None:
    with pytest.raises(CsvFormatError, match="expected columns"):
        parse_csv(header + "1,2,3,4\n")


# ── synthetic data ──────────────────────────────────────────────────────

MONDAY = t(28, 0)
NEXT_MONDAY = t(5, 0, month=10)


def synthetic(seed: int, symbol: str = "EURUSD") -> SyntheticSeries:
    return SyntheticSeries(DEFAULT_SPECS[symbol], seed, MONDAY, Timeframe.H1)


def test_synthetic_same_seed_same_bars() -> None:
    assert synthetic(7).bars(MONDAY, NEXT_MONDAY) == synthetic(7).bars(MONDAY, NEXT_MONDAY)


def test_synthetic_different_seed_differs() -> None:
    assert synthetic(7).bars(MONDAY, NEXT_MONDAY) != synthetic(8).bars(MONDAY, NEXT_MONDAY)


def test_synthetic_symbols_differ_for_same_seed() -> None:
    a = synthetic(7, "EURUSD").bars(MONDAY, MONDAY + timedelta(days=1))
    b = synthetic(7, "GBPUSD").bars(MONDAY, MONDAY + timedelta(days=1))
    assert [c.close for c in a] != [c.close for c in b]


def test_synthetic_random_access_matches_sequential() -> None:
    seq = synthetic(3).bars(MONDAY, NEXT_MONDAY)
    direct = synthetic(3)
    target = seq[50]
    assert direct.bar(direct.index_of(target.time)) == target


def test_synthetic_weekend_bars_absent() -> None:
    bars = synthetic(1).bars(MONDAY, NEXT_MONDAY)
    assert bars
    assert all(is_fx_market_open(c.time) for c in bars)
    assert not any(c.time.weekday() == 5 for c in bars)
    # Mon 00:00 → Fri 20:00 hourly (4*24 + 21 = 117) + Sun 21:00–23:00 (3).
    assert len(bars) == 117 + 3
    assert synthetic(1).bars(t(3, 0, month=10), t(4, 21, month=10)) == []


def test_synthetic_bars_are_valid_and_aligned() -> None:
    bars = synthetic(11).bars(MONDAY, NEXT_MONDAY)
    report = validate_candles(bars, Timeframe.H1)
    assert report.is_clean
    assert report.gaps == []
    assert all(c.close.as_tuple().exponent == -5 for c in bars)
    assert all(c.spread_points in (12, 36) for c in bars)
    assert bars[0].open == D("1.08500")


def test_synthetic_half_open_range() -> None:
    s = synthetic(1)
    bars = s.bars(t(28, 10, 30), t(28, 13))
    assert [c.time for c in bars] == [t(28, 11), t(28, 12)]
    assert s.bar(-1) is None


def test_synthetic_symbol_info() -> None:
    info = DEFAULT_SPECS["USDJPY"].symbol_info()
    assert info.point == D("0.001")
    assert info.pip_size == D("0.01")
    assert info.quote_currency == "JPY"


# ── candle store (MySQL) ────────────────────────────────────────────────


def _dataset(db: Session, **kw: Any) -> Dataset:
    values: dict[str, Any] = {
        "symbol": "EURUSD",
        "timeframe": Timeframe.M15,
        "source": DataSource.CSV,
        "source_ref": "test.csv",
    }
    values.update(kw)
    return get_or_create_dataset(db, **values)


def test_get_or_create_dataset_is_idempotent(db: Session) -> None:
    first = _dataset(db)
    second = _dataset(db)
    assert first.id == second.id
    other = _dataset(db, source_ref="other.csv")
    assert other.id != first.id


def test_upsert_candles_idempotent_with_checksum(db: Session) -> None:
    dataset = _dataset(db)
    candles = series(t(30, 9), Timeframe.M15, 10)
    assert upsert_candles(db, dataset, candles) == 10
    db.commit()
    stored = load_candles(db, dataset.id)
    assert len(stored) == 10
    assert [c.time for c in stored] == [c.time for c in candles]
    assert all(c.time.tzinfo is not None for c in stored)
    assert [c.close for c in stored] == [c.close for c in candles]  # numerically equal
    assert dataset.bar_count == 10
    assert dataset.first_bar == t(30, 9)
    assert dataset.last_bar == t(30, 11, 15)
    assert dataset.gap_count == 0
    first_checksum = dataset.checksum
    assert first_checksum == checksum(stored)
    assert len(first_checksum) == 64

    upsert_candles(db, dataset, candles)  # same data again
    db.commit()
    assert len(load_candles(db, dataset.id)) == 10
    assert dataset.bar_count == 10
    assert dataset.checksum == first_checksum


def test_upsert_updates_existing_bar_and_checksum(db: Session) -> None:
    dataset = _dataset(db)
    candles = series(t(30, 9), Timeframe.M15, 4)
    upsert_candles(db, dataset, candles)
    before = dataset.checksum
    changed = bar(candles[2].time, c="1.10080", vol=99)
    upsert_candles(db, dataset, [changed])
    db.commit()
    stored = load_candles(db, dataset.id)
    assert len(stored) == 4
    assert stored[2].close == D("1.10080")
    assert stored[2].tick_volume == 99
    assert dataset.checksum != before
    assert dataset.checksum == checksum(stored)


def test_store_records_gaps_and_range_loads(db: Session) -> None:
    dataset = _dataset(db)
    candles = [bar(t(30, 9)), bar(t(30, 9, 15)), bar(t(30, 10)), bar(t(30, 10, 15))]
    upsert_candles(db, dataset, candles)
    db.commit()
    assert dataset.gap_count == 1
    window = load_candles(db, dataset.id, start=t(30, 9, 15), end=t(30, 10, 15))
    assert [c.time for c in window] == [t(30, 9, 15), t(30, 10)]  # end exclusive


def test_store_isolates_datasets_and_deletes(db: Session) -> None:
    a = _dataset(db)
    b = _dataset(db, source=DataSource.SYNTHETIC, source_ref="42")
    upsert_candles(db, a, series(t(30, 9), Timeframe.M15, 3))
    upsert_candles(db, b, series(t(30, 9), Timeframe.M15, 5))
    db.commit()
    assert len(load_candles(db, a.id)) == 3
    assert len(load_candles(db, b.id)) == 5
    b_id = b.id
    delete_dataset(db, b)
    db.commit()
    assert load_candles(db, b_id) == []
    assert db.get(Dataset, b_id) is None
    assert len(load_candles(db, a.id)) == 3


def test_checksum_depends_on_content_and_order() -> None:
    bars = series(t(30, 9), Timeframe.M15, 3)
    assert checksum(bars) == checksum(list(bars))
    assert checksum(bars) != checksum(bars[::-1])
    assert checksum(bars) != checksum([*bars[:2], bar(bars[2].time, c="1.10060")])
    assert checksum([]) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
