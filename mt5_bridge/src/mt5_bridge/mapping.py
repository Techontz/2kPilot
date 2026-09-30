"""MT5 structs → protocol JSON, retcode mapping, enum mapping, decimal formatting."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from . import errors
from .timeutil import fmt_utc

CLIENT_ORDER_ID_RE = re.compile(r"^[a-z0-9]{8,24}$")
MT5_COMMENT_MAX = 31

# --- MetaTrader5 constants (real values; the module's own attributes are preferred) ---
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_TIMEOUT = 10012
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019

ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_LONGONLY = 1
SYMBOL_TRADE_MODE_SHORTONLY = 2
SYMBOL_TRADE_MODE_CLOSEONLY = 3
SYMBOL_TRADE_MODE_FULL = 4

SYMBOL_CALC_MODE_FOREX = 0
SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE = 5
METAL_CODES = frozenset({"XAU", "XAG", "XPT", "XPD"})

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7

ORDER_STATE_STARTED = 0
ORDER_STATE_PLACED = 1
ORDER_STATE_CANCELED = 2
ORDER_STATE_PARTIAL = 3
ORDER_STATE_FILLED = 4
ORDER_STATE_REJECTED = 5
ORDER_STATE_EXPIRED = 6

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3

DEAL_REASON_CLIENT = 0
DEAL_REASON_MOBILE = 1
DEAL_REASON_WEB = 2
DEAL_REASON_EXPERT = 3
DEAL_REASON_SL = 4
DEAL_REASON_TP = 5
DEAL_REASON_SO = 6

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
TIMEFRAME_CONST = {
    "M1": ("TIMEFRAME_M1", 1),
    "M5": ("TIMEFRAME_M5", 5),
    "M15": ("TIMEFRAME_M15", 15),
    "M30": ("TIMEFRAME_M30", 30),
    "H1": ("TIMEFRAME_H1", 16385),
    "H4": ("TIMEFRAME_H4", 16388),
    "D1": ("TIMEFRAME_D1", 16408),
}

RETCODE_MESSAGES = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10008: "Order placed",
    10009: "Request completed",
    10010: "Only part of the request was completed",
    10011: "Request processing error",
    10012: "Request canceled by timeout",
    10013: "Invalid request",
    10014: "Invalid volume in the request",
    10015: "Invalid price in the request",
    10016: "Invalid stops in the request",
    10017: "Trade is disabled",
    10018: "Market is closed",
    10019: "There is not enough money to complete the request",
    10020: "Prices changed",
    10021: "There are no quotes to process the request",
    10022: "Invalid order expiration date in the request",
    10023: "Order state changed",
    10024: "Too frequent requests",
    10025: "No changes in request",
    10026: "Autotrading disabled by server",
    10027: "Autotrading disabled by client terminal",
    10028: "Request locked for processing",
    10029: "Order or position frozen",
    10030: "Invalid order filling type",
    10031: "No connection with the trade server",
    10032: "Operation is allowed only for live accounts",
    10033: "The number of pending orders has reached the limit",
    10034: "The volume of orders and positions for the symbol has reached the limit",
    10035: "Incorrect or prohibited order type",
    10036: "Position with the specified identifier has already been closed",
    10038: "Close volume exceeds the current position volume",
    10039: "A close order already exists for the specified position",
    10040: "The number of open positions has reached the limit",
    10041: "Pending order activation request rejected, order canceled",
    10042: "Only long positions are allowed",
    10043: "Only short positions are allowed",
    10044: "Only position closing is allowed",
    10045: "Position closing is allowed only by FIFO rule",
    10046: "Opposite positions on a single account are disabled by the broker",
}


def const(mt5: Any, name: str, default: int) -> int:
    return int(getattr(mt5, name, default))


# --- decimals -------------------------------------------------------------------
def _dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(repr(float(value)))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def _no_neg_zero(d: Decimal) -> Decimal:
    return d.copy_abs() if d == 0 else d


def fmt_fixed(value: Any, places: int) -> str:
    """Format with exactly ``places`` decimals (banker's rounding)."""
    q = Decimal(1).scaleb(-max(places, 0))
    return format(_no_neg_zero(_dec(value).quantize(q, rounding=ROUND_HALF_EVEN)), "f")


def fmt_plain(value: Any) -> str:
    """Shortest exact representation without exponent, e.g. 1e-05 → "0.00001", 100.0 → "100"."""
    d = _no_neg_zero(_dec(value).normalize())
    s = format(d, "f")
    return s


def fmt_min2(value: Any, max_places: int = 8) -> str:
    """At least two decimals, up to ``max_places``; e.g. 1.0 → "1.00", 0.6712345 → "0.6712345"."""
    d = _dec(value).quantize(Decimal(1).scaleb(-max_places), rounding=ROUND_HALF_EVEN).normalize()
    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp > -2:
        d = d.quantize(Decimal("0.01"))
    return format(_no_neg_zero(d), "f")


def fmt_price(value: Any, digits: int | None) -> str | None:
    if value is None:
        return None
    return fmt_fixed(value, digits) if digits is not None else fmt_plain(value)


def fmt_opt_price(value: Any, digits: int | None) -> str | None:
    """SL/TP style: 0 means "not set" → null."""
    if value is None or float(value) == 0.0:
        return None
    return fmt_price(value, digits)


def volume_places(step: Any) -> int:
    exp = _dec(step).normalize().as_tuple().exponent
    return max(2, -exp) if isinstance(exp, int) else 2


def fmt_volume(value: Any, places: int = 2) -> str:
    return fmt_fixed(value, places)


def fmt_money(value: Any, places: int = 2) -> str:
    return fmt_fixed(value, places)


# --- client order id --------------------------------------------------------------
def build_comment(client_order_id: str, extra: str = "") -> str:
    extra = (extra or "").strip()
    if not extra:
        return client_order_id
    return f"{client_order_id} {extra}"[:MT5_COMMENT_MAX]


def parse_client_order_id(comment: Any) -> str | None:
    if not comment:
        return None
    token = str(comment).strip().split(" ", 1)[0]
    return token if CLIENT_ORDER_ID_RE.match(token) else None


# --- enums ------------------------------------------------------------------------
def environment(trade_mode: int, mt5: Any = None) -> str:
    if trade_mode == const(mt5, "ACCOUNT_TRADE_MODE_DEMO", ACCOUNT_TRADE_MODE_DEMO):
        return "DEMO"
    if trade_mode == const(mt5, "ACCOUNT_TRADE_MODE_REAL", ACCOUNT_TRADE_MODE_REAL):
        return "LIVE"
    return "UNKNOWN"


def select_filling(symbol_filling_mode: int, mt5: Any = None) -> int:
    """FOK, then IOC, then RETURN — based on the symbol's ``filling_mode`` bit flags."""
    fm = int(symbol_filling_mode or 0)
    if fm & const(mt5, "SYMBOL_FILLING_FOK", SYMBOL_FILLING_FOK):
        return const(mt5, "ORDER_FILLING_FOK", ORDER_FILLING_FOK)
    if fm & const(mt5, "SYMBOL_FILLING_IOC", SYMBOL_FILLING_IOC):
        return const(mt5, "ORDER_FILLING_IOC", ORDER_FILLING_IOC)
    return const(mt5, "ORDER_FILLING_RETURN", ORDER_FILLING_RETURN)


def deal_reason(reason: int) -> str:
    if reason in (DEAL_REASON_CLIENT, DEAL_REASON_MOBILE, DEAL_REASON_WEB):
        return "CLIENT"
    return {
        DEAL_REASON_EXPERT: "EXPERT",
        DEAL_REASON_SL: "SL",
        DEAL_REASON_TP: "TP",
        DEAL_REASON_SO: "SO",
    }.get(reason, "OTHER")


def deal_entry(entry: int) -> str:
    if entry == DEAL_ENTRY_IN:
        return "IN"
    if entry == DEAL_ENTRY_INOUT:
        return "INOUT"
    return "OUT"


def order_side_and_type(order_type: int) -> tuple[str, str]:
    return {
        ORDER_TYPE_BUY: ("BUY", "MARKET"),
        ORDER_TYPE_SELL: ("SELL", "MARKET"),
        ORDER_TYPE_BUY_LIMIT: ("BUY", "LIMIT"),
        ORDER_TYPE_SELL_LIMIT: ("SELL", "LIMIT"),
        ORDER_TYPE_BUY_STOP: ("BUY", "STOP"),
        ORDER_TYPE_SELL_STOP: ("SELL", "STOP"),
        ORDER_TYPE_BUY_STOP_LIMIT: ("BUY", "STOP"),
        ORDER_TYPE_SELL_STOP_LIMIT: ("SELL", "STOP"),
    }.get(order_type, ("BUY" if order_type % 2 == 0 else "SELL", "MARKET"))


def mt5_order_type(side: str, order_type: str) -> int:
    buy = side == "BUY"
    if order_type == "MARKET":
        return ORDER_TYPE_BUY if buy else ORDER_TYPE_SELL
    if order_type == "LIMIT":
        return ORDER_TYPE_BUY_LIMIT if buy else ORDER_TYPE_SELL_LIMIT
    return ORDER_TYPE_BUY_STOP if buy else ORDER_TYPE_SELL_STOP


def is_fx_or_metal(info: Any) -> bool:
    calc = int(getattr(info, "trade_calc_mode", -1))
    if calc in (SYMBOL_CALC_MODE_FOREX, SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE):
        return True
    return str(getattr(info, "currency_base", "")).upper() in METAL_CODES


def symbol_trade_allowed(trade_mode: int) -> bool:
    return trade_mode in (
        SYMBOL_TRADE_MODE_FULL,
        SYMBOL_TRADE_MODE_LONGONLY,
        SYMBOL_TRADE_MODE_SHORTONLY,
    )


# --- struct → JSON ------------------------------------------------------------------
def account_json(ai: Any, mt5: Any = None) -> dict[str, Any]:
    places = int(getattr(ai, "currency_digits", 2) or 2)
    return {
        "account_id": str(ai.login),
        "name": str(ai.name),
        "server": str(ai.server),
        "currency": str(ai.currency),
        "environment": environment(int(ai.trade_mode), mt5),
        "balance": fmt_money(ai.balance, places),
        "equity": fmt_money(ai.equity, places),
        "margin": fmt_money(ai.margin, places),
        "free_margin": fmt_money(ai.margin_free, places),
        "margin_level": fmt_money(ai.margin_level, 2),
        "leverage": int(ai.leverage),
        "trade_allowed": bool(ai.trade_allowed),
    }


def point_value(info: Any) -> Decimal:
    tick_size = _dec(info.trade_tick_size)
    if tick_size == 0:
        return Decimal(0)
    return _dec(info.trade_tick_value) * _dec(info.point) / tick_size


def symbol_json(info: Any) -> dict[str, Any]:
    return {
        "name": str(info.name),
        "description": str(info.description),
        "base_currency": str(info.currency_base),
        "quote_currency": str(info.currency_profit),
        "digits": int(info.digits),
        "point": fmt_plain(info.point),
        "contract_size": fmt_plain(info.trade_contract_size),
        "volume_min": fmt_plain(info.volume_min),
        "volume_max": fmt_plain(info.volume_max),
        "volume_step": fmt_plain(info.volume_step),
        "trade_allowed": symbol_trade_allowed(int(info.trade_mode)),
        "point_value": fmt_min2(point_value(info)),
    }


def quote_json(symbol: str, tick: Any, digits: int, offset: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "bid": fmt_fixed(tick.bid, digits),
        "ask": fmt_fixed(tick.ask, digits),
        "time": fmt_utc(int(tick.time) - offset),
    }


def candle_json(row: Any, digits: int, offset: int) -> dict[str, Any]:
    return {
        "time": fmt_utc(int(row["time"]) - offset),
        "open": fmt_fixed(row["open"], digits),
        "high": fmt_fixed(row["high"], digits),
        "low": fmt_fixed(row["low"], digits),
        "close": fmt_fixed(row["close"], digits),
        "tick_volume": int(row["tick_volume"]),
        "spread_points": int(row["spread"]),
    }


def position_json(
    p: Any, digits: int | None, offset: int, client_order_id: str | None, money_places: int = 2
) -> dict[str, Any]:
    return {
        "position_id": str(p.ticket),
        "symbol": str(p.symbol),
        "side": "BUY" if int(p.type) == POSITION_TYPE_BUY else "SELL",
        "volume": fmt_volume(p.volume),
        "open_price": fmt_price(p.price_open, digits),
        "open_time": fmt_utc(int(p.time) - offset),
        "stop_loss": fmt_opt_price(p.sl, digits),
        "take_profit": fmt_opt_price(p.tp, digits),
        "unrealized_pnl": fmt_money(p.profit, money_places),
        "swap": fmt_money(p.swap, money_places),
        "client_order_id": client_order_id,
    }


def order_json(o: Any, digits: int | None, offset: int) -> dict[str, Any]:
    side, otype = order_side_and_type(int(o.type))
    return {
        "order_id": str(o.ticket),
        "symbol": str(o.symbol),
        "side": side,
        "order_type": otype,
        "volume": fmt_volume(o.volume_current),
        "status": "PENDING",
        "price": fmt_price(o.price_open, digits),
        "stop_loss": fmt_opt_price(o.sl, digits),
        "take_profit": fmt_opt_price(o.tp, digits),
        "created_time": fmt_utc(int(o.time_setup) - offset),
        "client_order_id": parse_client_order_id(o.comment),
    }


def deal_json(d: Any, digits: int | None, offset: int, money_places: int = 2) -> dict[str, Any]:
    return {
        "deal_id": str(d.ticket),
        "order_id": str(d.order),
        "position_id": str(d.position_id),
        "symbol": str(d.symbol),
        "side": "BUY" if int(d.type) == DEAL_TYPE_BUY else "SELL",
        "entry": deal_entry(int(d.entry)),
        "volume": fmt_volume(d.volume),
        "price": fmt_price(d.price, digits),
        "time": fmt_utc(int(d.time) - offset),
        "profit": fmt_money(d.profit, money_places),
        "commission": fmt_money(d.commission, money_places),
        "swap": fmt_money(d.swap, money_places),
        "fee": fmt_money(getattr(d, "fee", 0.0), money_places),
        "client_order_id": parse_client_order_id(d.comment),
        "reason": deal_reason(int(d.reason)),
    }


def order_result(
    client_order_id: str | None,
    status: str,
    broker_order_id: Any = None,
    broker_position_id: Any = None,
    filled_volume: Any = 0.0,
    fill_price: Any = None,
    digits: int | None = None,
    broker_code: Any = None,
    broker_message: str | None = None,
) -> dict[str, Any]:
    return {
        "client_order_id": client_order_id,
        "status": status,
        "broker_order_id": str(broker_order_id) if broker_order_id else None,
        "broker_position_id": str(broker_position_id) if broker_position_id else None,
        "filled_volume": fmt_volume(filled_volume),
        "fill_price": fmt_price(fill_price, digits) if fill_price else None,
        "broker_code": str(broker_code) if broker_code is not None else None,
        "broker_message": broker_message,
    }


def retcode_message(retcode: int, comment: Any = None) -> str:
    c = str(comment).strip() if comment else ""
    return c or RETCODE_MESSAGES.get(retcode, f"Trade server return code {retcode}")


def retcode_error(retcode: int, comment: Any = None) -> errors.BridgeError | None:
    """Return the protocol error for a non-success retcode, ``None`` for success codes."""
    if retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE_PARTIAL):
        return None
    msg = retcode_message(retcode, comment)
    code = str(retcode)
    if retcode == TRADE_RETCODE_NO_MONEY:
        return errors.insufficient_margin(msg, code)
    if retcode == TRADE_RETCODE_MARKET_CLOSED:
        return errors.market_closed(msg, code)
    if retcode == TRADE_RETCODE_TIMEOUT:
        return errors.outcome_unknown(msg, code)
    return errors.rejected(msg, code)


def retcode_status(retcode: int) -> str:
    return {
        TRADE_RETCODE_DONE: "FILLED",
        TRADE_RETCODE_PLACED: "PENDING",
        TRADE_RETCODE_DONE_PARTIAL: "PARTIALLY_FILLED",
    }[retcode]


def weighted_price(deals: Iterable[Any]) -> tuple[float, float]:
    """(total volume, volume-weighted average price) of deals."""
    vol = Decimal(0)
    notional = Decimal(0)
    for d in deals:
        v = _dec(d.volume)
        vol += v
        notional += v * _dec(d.price)
    if vol == 0:
        return 0.0, 0.0
    return float(vol), float(notional / vol)
