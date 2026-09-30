"""Regression: the engine's history window must always contain the bars a
strategy needs, even when it straddles two weekends (found in UI review)."""

from datetime import UTC, datetime, timedelta

import pytest

from fxrobot.broker_engine.adapters.paper_market import SyntheticMarket
from fxrobot.domain.market import Timeframe
from fxrobot.market_data.sessions import calendar_span
from fxrobot.trading_engine.runner import history_start


@pytest.mark.parametrize("day", range(1, 15))
def test_history_window_covers_required_bars(day: int) -> None:
    market = SyntheticMarket(
        seed=42,
        symbols=["EURUSD"],
        start=datetime(2026, 9, day, 1, 0, tzinfo=UTC),
        seconds_per_bar=0,
    )
    now = market.now()
    for tf, bars in ((Timeframe.H1, 150), (Timeframe.H4, 415), (Timeframe.D1, 60)):
        got = market.candles("EURUSD", tf, history_start(now, tf, bars), now)
        assert len(got) >= bars, (tf, len(got))


def test_calendar_span_scales_with_weekends() -> None:
    assert calendar_span(3600, 120) == timedelta(hours=168) + timedelta(days=3)
