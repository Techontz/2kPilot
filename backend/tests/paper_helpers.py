"""Helpers for building deterministic paper brokers in tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fxrobot.broker_engine.adapters.paper import FaultInjector, PaperBroker, PaperConfig
from fxrobot.broker_engine.adapters.paper_market import SyntheticMarket

# A Wednesday, market open. Real "now" is far later, so stepping is never capped.
SIM_START = datetime(2025, 3, 5, 10, 0, tzinfo=UTC)


def make_market(symbols: tuple[str, ...] = ("EURUSD", "USDJPY"), seed: int = 7) -> SyntheticMarket:
    return SyntheticMarket(seed=seed, symbols=symbols, start=SIM_START, seconds_per_bar=0)


def make_paper(
    symbols: tuple[str, ...] = ("EURUSD", "USDJPY"),
    *,
    balance: str = "10000",
    commission: str = "3.5",
    faults: FaultInjector | None = None,
) -> PaperBroker:
    broker = PaperBroker(
        make_market(symbols),
        PaperConfig(initial_balance=Decimal(balance), commission_per_lot=Decimal(commission)),
        faults=faults,
    )
    broker.connect()
    return broker
