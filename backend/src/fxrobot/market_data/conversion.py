"""Currency conversion and pip/point values from available quotes."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from fxrobot.domain.market import Quote, SymbolInfo

QuoteLookup = Callable[[str], Quote | None]


def conversion_rate(from_ccy: str, to_ccy: str, lookup: QuoteLookup) -> Decimal | None:
    """Rate to convert an amount in `from_ccy` into `to_ccy`, or None if unknown.

    Tries the direct pair, the inverse pair, then a cross via USD. Mid prices
    are used; returning None lets callers fail safe instead of guessing.
    """
    if from_ccy == to_ccy:
        return Decimal(1)
    direct = lookup(from_ccy + to_ccy)
    if direct and direct.mid > 0:
        return direct.mid
    inverse = lookup(to_ccy + from_ccy)
    if inverse and inverse.mid > 0:
        return Decimal(1) / inverse.mid
    if "USD" not in (from_ccy, to_ccy):
        first = conversion_rate(from_ccy, "USD", lookup)
        second = conversion_rate("USD", to_ccy, lookup)
        if first is not None and second is not None:
            return first * second
    return None


def point_value(symbol: SymbolInfo, account_ccy: str, lookup: QuoteLookup) -> Decimal | None:
    """Value of a one-point move for 1.00 lot, in account currency."""
    if symbol.point_value is not None and symbol.point_value > 0:
        return symbol.point_value
    rate = conversion_rate(symbol.quote_currency, account_ccy, lookup)
    if rate is None:
        return None
    return symbol.contract_size * symbol.point * rate


def pip_value(symbol: SymbolInfo, account_ccy: str, lookup: QuoteLookup) -> Decimal | None:
    value = point_value(symbol, account_ccy, lookup)
    if value is None:
        return None
    return value * (symbol.pip_size / symbol.point)


def price_to_pips(distance: Decimal, symbol: SymbolInfo) -> Decimal:
    return abs(distance) / symbol.pip_size


def profit_in_account(
    symbol: SymbolInfo,
    side_sign: int,
    volume: Decimal,
    entry: Decimal,
    exit_price: Decimal,
    account_ccy: str,
    lookup: QuoteLookup,
) -> Decimal | None:
    quote_ccy_pnl = (exit_price - entry) * side_sign * volume * symbol.contract_size
    rate = conversion_rate(symbol.quote_currency, account_ccy, lookup)
    return None if rate is None else quote_ccy_pnl * rate
