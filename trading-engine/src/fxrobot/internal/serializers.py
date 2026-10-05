"""JSON shapes returned to Laravel. Decimals are strings (never floats)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fxrobot.broker_engine.models import AccountInfo, Candle, Quote
from fxrobot.domain.market import SymbolInfo


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {k: plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [plain(v) for v in value]
    return value


def account(info: AccountInfo) -> dict[str, Any]:
    return {
        "account_id": info.account_id,
        "name": info.name,
        "server": info.server,
        "currency": info.currency,
        "environment": info.environment.value,
        "balance": plain(info.balance),
        "equity": plain(info.equity),
        "margin": plain(info.margin),
        "free_margin": plain(info.free_margin),
        "leverage": info.leverage,
        "trade_allowed": info.trade_allowed,
    }


def symbol(info: SymbolInfo) -> dict[str, Any]:
    return {
        "name": info.name,
        "canonical": info.canonical_name,
        "description": info.description,
        "category": info.category,
        "base_currency": info.base_currency,
        "quote_currency": info.quote_currency,
        "digits": info.digits,
        "point": plain(info.point),
        "pip_size": plain(info.pip_size),
        "contract_size": plain(info.contract_size),
        "volume_min": plain(info.volume_min),
        "volume_max": plain(info.volume_max),
        "volume_step": plain(info.volume_step),
        "trade_allowed": info.trade_allowed,
        "market_open": info.market_open,
    }


def quote(q: Quote) -> dict[str, Any]:
    return {
        "symbol": q.symbol,
        "bid": plain(q.bid),
        "ask": plain(q.ask),
        "spread": plain(q.spread),
        "time": q.time.isoformat(),
    }


def candle(c: Candle) -> dict[str, Any]:
    return {
        "time": c.time.isoformat(),
        "open": plain(c.open),
        "high": plain(c.high),
        "low": plain(c.low),
        "close": plain(c.close),
        "volume": c.tick_volume,
    }
