from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mt5_bridge import mapping as m
from mt5_bridge.timeutil import fmt_utc, fx_market_probably_open, offset_from_tick, parse_utc


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        (1.08512, 5, "1.08512"),
        (1.0851, 5, "1.08510"),
        (-0.0, 2, "0.00"),
        (-0.001, 2, "0.00"),
        (10012.5, 2, "10012.50"),
        (0.1 + 0.2, 2, "0.30"),
    ],
)
def test_fmt_fixed(value: float, places: int, expected: str) -> None:
    assert m.fmt_fixed(value, places) == expected


def test_fmt_plain_and_min2() -> None:
    assert m.fmt_plain(1e-05) == "0.00001"
    assert m.fmt_plain(100000.0) == "100000"
    assert m.fmt_plain(0.01) == "0.01"
    assert m.fmt_min2(1.0) == "1.00"
    assert m.fmt_min2(0.66891234) == "0.66891234"


def test_point_value() -> None:
    info = SimpleNamespace(trade_tick_value=0.5, trade_tick_size=0.00005, point=0.00001)
    assert m.fmt_min2(m.point_value(info)) == "0.10"
    zero = SimpleNamespace(trade_tick_value=1.0, trade_tick_size=0.0, point=0.00001)
    assert m.point_value(zero) == 0


def test_client_order_id_parsing() -> None:
    assert m.parse_client_order_id("fx0123456789abcdefghijkl") == "fx0123456789abcdefghijkl"
    assert m.parse_client_order_id("abcdefgh note") == "abcdefgh"
    assert m.parse_client_order_id("[tp 1.09100]") is None
    assert m.parse_client_order_id("") is None
    assert m.parse_client_order_id(None) is None
    assert m.parse_client_order_id("ABCDEFGH") is None


def test_retcode_mapping() -> None:
    assert m.retcode_error(10009) is None
    assert m.retcode_error(10008) is None
    assert m.retcode_error(10010) is None
    for code, (status, err_code) in {
        10019: (409, "insufficient_margin"),
        10018: (409, "market_closed"),
        10012: (504, "outcome_unknown"),
        10016: (409, "rejected"),
        10006: (409, "rejected"),
    }.items():
        err = m.retcode_error(code)
        assert err is not None
        assert (err.status_code, err.code, err.broker_code) == (status, err_code, str(code))


def test_time_helpers() -> None:
    assert fmt_utc(0) == "1970-01-01T00:00:00Z"
    assert parse_utc("2026-10-01T13:00:00Z") == datetime(2026, 10, 1, 13, tzinfo=UTC)
    for bad in ("2026-10-01T13:00:00", "2026-10-01T13:00:00+03:00", "yesterday"):
        with pytest.raises(ValueError, match="ISO-8601"):
            parse_utc(bad)
    now = datetime(2026, 10, 1, 13, tzinfo=UTC).timestamp()
    assert offset_from_tick(now + 10800 - 2, now) == 10800
    assert offset_from_tick(now - 3600 - 1, now) == -3600
    assert offset_from_tick(now + 10800 - 500, now) is None
    assert fx_market_probably_open(now)
    assert not fx_market_probably_open(datetime(2026, 10, 3, 12, tzinfo=UTC).timestamp())
    assert not fx_market_probably_open(datetime(2026, 10, 4, 20, tzinfo=UTC).timestamp())
    assert fx_market_probably_open(datetime(2026, 10, 4, 22, 30, tzinfo=UTC).timestamp())
    assert not fx_market_probably_open(datetime(2026, 10, 2, 21, 30, tzinfo=UTC).timestamp())
