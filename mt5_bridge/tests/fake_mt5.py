"""A realistic in-memory fake of the ``MetaTrader5`` Python package.

It mirrors the real API's shapes: named-tuple structs, tuples from ``*_get``
functions, ``None`` + ``last_error()`` on failure, a numpy structured array from
``copy_rates_range``, trade-server times encoded as epoch seconds, and the real
constant values. Behaviour can be scripted per test (retcodes, ``None`` results,
delays, disconnects, …).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

import numpy as np

# --------------------------------------------------------------------------- constants
TIMEFRAME_M1 = 1
TIMEFRAME_M5 = 5
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 16385
TIMEFRAME_H4 = 16388
TIMEFRAME_D1 = 16408

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8
TRADE_ACTION_CLOSE_BY = 10

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_TIME_GTC = 0

ORDER_STATE_STARTED = 0
ORDER_STATE_PLACED = 1
ORDER_STATE_CANCELED = 2
ORDER_STATE_PARTIAL = 3
ORDER_STATE_FILLED = 4
ORDER_STATE_REJECTED = 5

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_FULL = 4
SYMBOL_CALC_MODE_FOREX = 0
SYMBOL_CALC_MODE_CFD = 2

ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_TYPE_BALANCE = 2
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_REASON_CLIENT = 0
DEAL_REASON_EXPERT = 3
DEAL_REASON_SL = 4
DEAL_REASON_TP = 5
DEAL_REASON_SO = 6

TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_TIMEOUT = 10012
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019

RES_S_OK = 1
RES_E_AUTH_FAILED = -6
RES_E_INTERNAL_FAIL_CONNECT = -10004
RES_E_INTERNAL_FAIL_INIT = -10003

RATE_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<u8"),
        ("spread", "<i4"),
        ("real_volume", "<u8"),
    ]
)


# --------------------------------------------------------------------------- structs
class AccountInfo(NamedTuple):
    login: int
    trade_mode: int
    leverage: int
    limit_orders: int
    margin_so_mode: int
    trade_allowed: bool
    trade_expert: bool
    margin_mode: int
    currency_digits: int
    fifo_close: bool
    balance: float
    credit: float
    profit: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    margin_so_call: float
    margin_so_so: float
    name: str
    server: str
    currency: str
    company: str


class TerminalInfo(NamedTuple):
    connected: bool
    trade_allowed: bool
    tradeapi_disabled: bool
    build: int
    maxbars: int
    company: str
    name: str
    path: str


class SymbolInfo(NamedTuple):
    name: str
    description: str
    path: str
    visible: bool
    select: bool
    digits: int
    spread: int
    trade_calc_mode: int
    trade_mode: int
    filling_mode: int
    time: int
    bid: float
    ask: float
    point: float
    trade_tick_value: float
    trade_tick_size: float
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    currency_base: str
    currency_profit: str
    currency_margin: str


class Tick(NamedTuple):
    time: int
    bid: float
    ask: float
    last: float
    volume: int
    time_msc: int
    flags: int
    volume_real: float


class TradePosition(NamedTuple):
    ticket: int
    time: int
    time_msc: int
    time_update: int
    time_update_msc: int
    type: int
    magic: int
    identifier: int
    reason: int
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    swap: float
    profit: float
    symbol: str
    comment: str
    external_id: str


class TradeOrder(NamedTuple):
    ticket: int
    time_setup: int
    time_setup_msc: int
    time_done: int
    time_done_msc: int
    time_expiration: int
    type: int
    type_time: int
    type_filling: int
    state: int
    magic: int
    position_id: int
    position_by_id: int
    reason: int
    volume_initial: float
    volume_current: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    price_stoplimit: float
    symbol: str
    comment: str
    external_id: str


class TradeDeal(NamedTuple):
    ticket: int
    order: int
    time: int
    time_msc: int
    type: int
    entry: int
    magic: int
    position_id: int
    reason: int
    volume: float
    price: float
    commission: float
    swap: float
    profit: float
    fee: float
    symbol: str
    comment: str
    external_id: str


class OrderSendResult(NamedTuple):
    retcode: int
    deal: int
    order: int
    volume: float
    price: float
    bid: float
    ask: float
    comment: str
    request_id: int
    retcode_external: int
    request: Any


@dataclass
class SendBehaviour:
    """Scripted outcome for the next ``order_send`` call."""

    retcode: int | None = None  # force this retcode (nothing executed unless success)
    return_none: bool = False  # return None (optionally after executing)
    execute: bool = True  # when return_none: whether the trade still executes
    raise_exc: bool = False
    delay: float = 0.0
    fill_ratio: float = 1.0  # < 1 → DONE_PARTIAL
    disconnect: bool = False  # drop the terminal connection (IPC error) and return None


def _symbol(
    name: str,
    digits: int,
    bid: float,
    spread_points: int,
    *,
    base: str,
    quote: str,
    tick_value: float = 1.0,
    contract: float = 100000.0,
    calc: int = 0,
    filling: int = SYMBOL_FILLING_FOK | SYMBOL_FILLING_IOC,
    visible: bool = True,
    trade_mode: int = SYMBOL_TRADE_MODE_FULL,
    description: str = "",
) -> SymbolInfo:
    point = 10.0**-digits
    return SymbolInfo(
        name=name,
        description=description or f"{base} vs {quote}",
        path=f"Forex\\{name}",
        visible=visible,
        select=visible,
        digits=digits,
        spread=spread_points,
        trade_calc_mode=calc,
        trade_mode=trade_mode,
        filling_mode=filling,
        time=0,
        bid=bid,
        ask=round(bid + spread_points * point, digits),
        point=point,
        trade_tick_value=tick_value,
        trade_tick_size=point,
        trade_contract_size=contract,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        currency_base=base,
        currency_profit=quote,
        currency_margin=base,
    )


@dataclass
class FakeMT5:
    clock: Callable[[], float] = time.time
    server_offset: int = 3 * 3600
    # scriptable state
    installed: bool = True
    initialize_ok: bool = True
    connected: bool = True
    logged_in: bool = True
    valid_login: int = 5012345
    valid_password: str = "correct-horse"
    valid_server: str = "MetaQuotes-Demo"
    trade_mode: int = ACCOUNT_TRADE_MODE_DEMO
    balance: float = 10000.0
    leverage: int = 100
    market_closed: bool = False
    tick_lag: float = 0.4  # seconds a tick lags "now"
    call_delay: float = 0.0  # artificial latency for every API call
    send_behaviours: list[SendBehaviour] = field(default_factory=list)
    # internals / instrumentation
    symbols: dict[str, SymbolInfo] = field(default_factory=dict)
    positions: dict[int, TradePosition] = field(default_factory=dict)
    orders: dict[int, TradeOrder] = field(default_factory=dict)
    history_orders: dict[int, TradeOrder] = field(default_factory=dict)
    history_deals: dict[int, TradeDeal] = field(default_factory=dict)
    rates: dict[tuple[str, int], list[tuple[int, float, float, float, float, int, int, int]]] = (
        field(default_factory=dict)
    )
    order_send_calls: list[dict[str, Any]] = field(default_factory=list)
    login_calls: list[tuple[int, str]] = field(default_factory=list)
    thread_ids: set[int] = field(default_factory=set)
    max_concurrency: int = 0
    _active: int = 0
    _initialized: bool = False
    _last_error: tuple[int, str] = (RES_S_OK, "Success")
    _next_ticket: int = 100000
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if not self.symbols:
            for s in (
                _symbol(
                    "EURUSD",
                    5,
                    1.08500,
                    12,
                    base="EUR",
                    quote="USD",
                    description="Euro vs US Dollar",
                ),
                _symbol("USDJPY", 3, 149.500, 15, base="USD", quote="JPY", tick_value=0.6689),
                _symbol(
                    "XAUUSD",
                    2,
                    2650.00,
                    20,
                    base="XAU",
                    quote="USD",
                    contract=100.0,
                    calc=SYMBOL_CALC_MODE_CFD,
                    tick_value=1.0,
                ),
                _symbol(
                    "GBPUSD",
                    5,
                    1.27000,
                    14,
                    base="GBP",
                    quote="USD",
                    visible=False,
                    filling=SYMBOL_FILLING_IOC,
                ),
                _symbol(
                    "US500",
                    2,
                    5800.0,
                    50,
                    base="USD",
                    quote="USD",
                    contract=1.0,
                    calc=SYMBOL_CALC_MODE_CFD,
                ),
                _symbol(
                    "EURCHF",
                    5,
                    0.94000,
                    20,
                    base="EUR",
                    quote="CHF",
                    trade_mode=SYMBOL_TRADE_MODE_DISABLED,
                ),
            ):
                self.symbols[s.name] = s

    # ---------------------------------------------------------------- instrumentation
    def _enter(self) -> None:
        with self._lock:
            self._active += 1
            self.max_concurrency = max(self.max_concurrency, self._active)
            self.thread_ids.add(threading.get_ident())
        if self.call_delay:
            time.sleep(self.call_delay)

    def _exit(self) -> None:
        with self._lock:
            self._active -= 1

    def _ok(self) -> None:
        self._last_error = (RES_S_OK, "Success")

    def _fail(self, code: int, msg: str) -> None:
        self._last_error = (code, msg)

    def _usable(self) -> bool:
        if not self._initialized:
            self._fail(-10004, "No IPC connection")
            return False
        return True

    def server_now(self) -> int:
        return int(self.clock()) + self.server_offset

    def _ticket(self) -> int:
        self._next_ticket += 1
        return self._next_ticket

    # ---------------------------------------------------------------- session API
    def initialize(
        self,
        path: str | None = None,
        *,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        timeout: int = 60000,
        portable: bool = False,
    ) -> bool:
        self._enter()
        try:
            if not self.initialize_ok:
                self._fail(
                    RES_E_INTERNAL_FAIL_INIT, "IPC initialize failed, MetaTrader 5 x64 not found"
                )
                return False
            self._initialized = True
            if login is not None:
                self.login_calls.append((login, server or ""))
                if not self._check_credentials(login, password, server):
                    self._initialized = False
                    self._fail(RES_E_AUTH_FAILED, "Terminal: Authorization failed")
                    return False
                self.logged_in = True
            self._ok()
            return True
        finally:
            self._exit()

    def _check_credentials(self, login: int, password: str | None, server: str | None) -> bool:
        return (
            login == self.valid_login
            and password == self.valid_password
            and server == self.valid_server
        )

    def login(
        self,
        login: int,
        password: str | None = None,
        server: str | None = None,
        timeout: int = 60000,
    ) -> bool:
        self._enter()
        try:
            if not self._usable():
                return False
            self.login_calls.append((login, server or ""))
            if not self._check_credentials(login, password, server):
                self._fail(RES_E_AUTH_FAILED, "Terminal: Authorization failed")
                return False
            self.logged_in = True
            self._ok()
            return True
        finally:
            self._exit()

    def shutdown(self) -> None:
        self._enter()
        try:
            self._initialized = False
        finally:
            self._exit()

    def last_error(self) -> tuple[int, str]:
        return self._last_error

    def version(self) -> tuple[int, int, str]:
        return (500, 4410, "01 Oct 2026")

    def terminal_info(self) -> TerminalInfo | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            return TerminalInfo(
                connected=self.connected,
                trade_allowed=True,
                tradeapi_disabled=False,
                build=4410,
                maxbars=100000,
                company="MetaQuotes Ltd.",
                name="MetaTrader 5",
                path="C:\\Program Files\\MetaTrader 5",
            )
        finally:
            self._exit()

    def account_info(self) -> AccountInfo | None:
        self._enter()
        try:
            if not self._usable() or not self.logged_in:
                if self._initialized:
                    self._fail(-1, "Terminal: Call failed")
                return None
            self._ok()
            return self._account()
        finally:
            self._exit()

    def _account(self) -> AccountInfo:
        profit = sum(p.profit for p in self.positions.values())
        margin = sum(
            self._margin(p.symbol, p.volume, p.price_open) for p in self.positions.values()
        )
        equity = self.balance + profit
        return AccountInfo(
            login=self.valid_login,
            trade_mode=self.trade_mode,
            leverage=self.leverage,
            limit_orders=200,
            margin_so_mode=0,
            trade_allowed=True,
            trade_expert=True,
            margin_mode=2,
            currency_digits=2,
            fifo_close=False,
            balance=self.balance,
            credit=0.0,
            profit=profit,
            equity=equity,
            margin=margin,
            margin_free=equity - margin,
            margin_level=(equity / margin * 100) if margin else 0.0,
            margin_so_call=50.0,
            margin_so_so=30.0,
            name="Conrad",
            server=self.valid_server,
            currency="USD",
            company="MetaQuotes Ltd.",
        )

    def _margin(self, symbol: str, volume: float, price: float) -> float:
        info = self.symbols[symbol]
        return volume * info.trade_contract_size * price / self.leverage

    # ---------------------------------------------------------------- symbols / quotes
    def symbols_get(self, group: str | None = None) -> tuple[SymbolInfo, ...] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            items = list(self.symbols.values())
            if group:
                needle = group.strip("*")
                items = [s for s in items if needle in s.name]
            return tuple(items)
        finally:
            self._exit()

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        self._enter()
        try:
            if not self._usable():
                return None
            info = self.symbols.get(symbol)
            if info is None:
                self._fail(-4, "Terminal: Not found")
                return None
            self._ok()
            return info._replace(time=self.server_now())
        finally:
            self._exit()

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        self._enter()
        try:
            if not self._usable() or symbol not in self.symbols:
                return False
            self.symbols[symbol] = self.symbols[symbol]._replace(visible=enable, select=enable)
            return True
        finally:
            self._exit()

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        self._enter()
        try:
            if not self._usable():
                return None
            info = self.symbols.get(symbol)
            if info is None or not info.visible:
                self._fail(-4, "Terminal: Not found")
                return None
            self._ok()
            t = self.clock() - self.tick_lag + self.server_offset
            return Tick(
                time=int(t),
                bid=info.bid,
                ask=info.ask,
                last=0.0,
                volume=0,
                time_msc=int(t * 1000),
                flags=6,
                volume_real=0.0,
            )
        finally:
            self._exit()

    def set_price(self, symbol: str, bid: float) -> None:
        info = self.symbols[symbol]
        self.symbols[symbol] = info._replace(
            bid=bid, ask=round(bid + info.spread * info.point, info.digits)
        )

    # ---------------------------------------------------------------- rates
    def add_bars(
        self,
        symbol: str,
        timeframe: int,
        tf_seconds: int,
        first_server_time: int,
        count: int,
        start_price: float = 1.08000,
    ) -> None:
        bars = self.rates.setdefault((symbol, timeframe), [])
        price = start_price
        for i in range(count):
            o = price
            c = round(o + (0.0002 if i % 2 == 0 else -0.0001), 5)
            bars.append(
                (
                    first_server_time + i * tf_seconds,
                    o,
                    max(o, c) + 0.0003,
                    min(o, c) - 0.0002,
                    c,
                    100 + i,
                    9,
                    0,
                )
            )
            price = c

    def copy_rates_range(
        self, symbol: str, timeframe: int, date_from: datetime | int, date_to: datetime | int
    ) -> np.ndarray[Any, Any] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            if symbol not in self.symbols:
                self._fail(-4, "Terminal: Not found")
                return None
            f = int(date_from.timestamp()) if isinstance(date_from, datetime) else date_from
            t = int(date_to.timestamp()) if isinstance(date_to, datetime) else date_to
            rows = [b for b in self.rates.get((symbol, timeframe), []) if f <= b[0] <= t]
            self._ok()
            return np.array(rows, dtype=RATE_DTYPE)
        finally:
            self._exit()

    # ---------------------------------------------------------------- trading state
    def positions_get(
        self, symbol: str | None = None, group: str | None = None, ticket: int | None = None
    ) -> tuple[TradePosition, ...] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            items = list(self.positions.values())
            if ticket is not None:
                items = [p for p in items if p.ticket == ticket]
            if symbol is not None:
                items = [p for p in items if p.symbol == symbol]
            return tuple(items)
        finally:
            self._exit()

    def orders_get(
        self, symbol: str | None = None, group: str | None = None, ticket: int | None = None
    ) -> tuple[TradeOrder, ...] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            items = list(self.orders.values())
            if ticket is not None:
                items = [o for o in items if o.ticket == ticket]
            return tuple(items)
        finally:
            self._exit()

    def history_orders_get(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        group: str | None = None,
        ticket: int | None = None,
        position: int | None = None,
    ) -> tuple[TradeOrder, ...] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            items = list(self.history_orders.values())
            if ticket is not None:
                return tuple(o for o in items if o.ticket == ticket)
            if position is not None:
                return tuple(o for o in items if o.position_id == position)
            assert date_from is not None
            assert date_to is not None
            f, t = int(date_from.timestamp()), int(date_to.timestamp())
            return tuple(o for o in items if f <= o.time_setup <= t)
        finally:
            self._exit()

    def history_deals_get(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        group: str | None = None,
        ticket: int | None = None,
        position: int | None = None,
    ) -> tuple[TradeDeal, ...] | None:
        self._enter()
        try:
            if not self._usable():
                return None
            self._ok()
            items = list(self.history_deals.values())
            if ticket is not None:
                return tuple(d for d in items if d.order == ticket)
            if position is not None:
                return tuple(d for d in items if d.position_id == position)
            assert date_from is not None
            assert date_to is not None
            f, t = int(date_from.timestamp()), int(date_to.timestamp())
            return tuple(d for d in items if f <= d.time <= t)
        finally:
            self._exit()

    # ---------------------------------------------------------------- helpers for tests
    def add_deal(self, **kw: Any) -> TradeDeal:
        base: dict[str, Any] = {
            "ticket": self._ticket(),
            "order": 0,
            "time": self.server_now(),
            "time_msc": 0,
            "type": DEAL_TYPE_BUY,
            "entry": DEAL_ENTRY_IN,
            "magic": 0,
            "position_id": 0,
            "reason": DEAL_REASON_CLIENT,
            "volume": 0.1,
            "price": 1.085,
            "commission": 0.0,
            "swap": 0.0,
            "profit": 0.0,
            "fee": 0.0,
            "symbol": "EURUSD",
            "comment": "",
            "external_id": "",
        }
        base.update(kw)
        deal = TradeDeal(**base)
        self.history_deals[deal.ticket] = deal
        return deal

    def add_position(self, **kw: Any) -> TradePosition:
        ticket = kw.pop("ticket", None) or self._ticket()
        base: dict[str, Any] = {
            "ticket": ticket,
            "time": self.server_now(),
            "time_msc": 0,
            "time_update": 0,
            "time_update_msc": 0,
            "type": POSITION_TYPE_BUY,
            "magic": 0,
            "identifier": ticket,
            "reason": 0,
            "volume": 0.1,
            "price_open": 1.085,
            "sl": 0.0,
            "tp": 0.0,
            "price_current": 1.085,
            "swap": 0.0,
            "profit": 0.0,
            "symbol": "EURUSD",
            "comment": "",
            "external_id": "",
        }
        base.update(kw)
        pos = TradePosition(**base)
        self.positions[pos.ticket] = pos
        return pos

    # ---------------------------------------------------------------- order_send
    def order_send(self, request: dict[str, Any]) -> OrderSendResult | None:
        self._enter()
        try:
            self.order_send_calls.append(dict(request))
            if not self._usable():
                return None
            b = self.send_behaviours.pop(0) if self.send_behaviours else SendBehaviour()
            if b.delay:
                time.sleep(b.delay)
            if b.raise_exc:
                raise RuntimeError("IPC broken")
            if b.disconnect:
                self._initialized = False
                self._fail(-10004, "No IPC connection")
                return None
            if b.return_none:
                if b.execute:
                    self._execute(request, b)
                self._fail(-10005, "IPC timeout")
                return None
            if b.retcode is not None and b.retcode not in (
                TRADE_RETCODE_DONE,
                TRADE_RETCODE_PLACED,
                TRADE_RETCODE_DONE_PARTIAL,
            ):
                return self._result(b.retcode, request)
            return self._execute(request, b)
        finally:
            self._exit()

    def _result(
        self,
        retcode: int,
        request: dict[str, Any],
        *,
        deal: int = 0,
        order: int = 0,
        volume: float = 0.0,
        price: float = 0.0,
        comment: str = "",
    ) -> OrderSendResult:
        self._ok()
        return OrderSendResult(
            retcode=retcode,
            deal=deal,
            order=order,
            volume=volume,
            price=price,
            bid=0.0,
            ask=0.0,
            comment=comment,
            request_id=1,
            retcode_external=0,
            request=request,
        )

    def _execute(self, r: dict[str, Any], b: SendBehaviour) -> OrderSendResult:
        action = r["action"]
        if action == TRADE_ACTION_DEAL:
            return self._deal(r, b)
        if action == TRADE_ACTION_PENDING:
            return self._pending(r)
        if action == TRADE_ACTION_SLTP:
            pos = self.positions.get(r["position"])
            if pos is None:
                return self._result(10036, r)
            self.positions[pos.ticket] = pos._replace(sl=r.get("sl", 0.0), tp=r.get("tp", 0.0))
            return self._result(TRADE_RETCODE_DONE, r, comment="Request executed")
        if action == TRADE_ACTION_MODIFY:
            o = self.orders.get(r["order"])
            if o is None:
                return self._result(10013, r)
            self.orders[o.ticket] = o._replace(
                price_open=r["price"], sl=r.get("sl", 0.0), tp=r.get("tp", 0.0)
            )
            return self._result(TRADE_RETCODE_DONE, r, order=o.ticket, comment="Request executed")
        if action == TRADE_ACTION_REMOVE:
            o = self.orders.pop(r["order"], None)
            if o is None:
                return self._result(10013, r)
            self.history_orders[o.ticket] = o._replace(
                state=ORDER_STATE_CANCELED, time_done=self.server_now()
            )
            return self._result(TRADE_RETCODE_DONE, r, order=o.ticket, comment="Request executed")
        return self._result(10013, r)

    def _validate(self, r: dict[str, Any], price: float, is_buy: bool) -> int | None:
        info = self.symbols[r["symbol"]]
        vol = r["volume"]
        if vol < info.volume_min or vol > info.volume_max:
            return TRADE_RETCODE_INVALID_VOLUME
        if self.market_closed:
            return TRADE_RETCODE_MARKET_CLOSED
        sl, tp = r.get("sl", 0.0), r.get("tp", 0.0)
        if is_buy and ((sl and sl >= price) or (tp and tp <= price)):
            return TRADE_RETCODE_INVALID_STOPS
        if not is_buy and ((sl and sl <= price) or (tp and tp >= price)):
            return TRADE_RETCODE_INVALID_STOPS
        if not r.get("position"):
            acct = self._account()
            if self._margin(r["symbol"], vol, price) > acct.margin_free:
                return TRADE_RETCODE_NO_MONEY
        return None

    def _deal(self, r: dict[str, Any], b: SendBehaviour) -> OrderSendResult:
        info = self.symbols[r["symbol"]]
        is_buy = r["type"] == ORDER_TYPE_BUY
        price = info.ask if is_buy else info.bid
        if not r.get("position"):
            err = self._validate(r, price, is_buy)
            if err is not None:
                return self._result(err, r)
        elif self.market_closed:
            return self._result(TRADE_RETCODE_MARKET_CLOSED, r)
        now = self.server_now()
        order_ticket = self._ticket()
        volume = round(r["volume"] * b.fill_ratio, 2)
        retcode = TRADE_RETCODE_DONE if b.fill_ratio >= 1 else TRADE_RETCODE_DONE_PARTIAL
        deal_ticket = self._ticket()
        if r.get("position"):
            pos = self.positions[r["position"]]
            position_id = pos.identifier
            entry = DEAL_ENTRY_OUT
            direction = 1 if pos.type == POSITION_TYPE_BUY else -1
            profit = round(
                (price - pos.price_open) * direction * volume * info.trade_contract_size, 2
            )
            remaining = round(pos.volume - volume, 2)
            if remaining <= 0:
                del self.positions[pos.ticket]
            else:
                self.positions[pos.ticket] = pos._replace(volume=remaining)
            self.balance += profit
        else:
            position_id = order_ticket
            entry = DEAL_ENTRY_IN
            profit = 0.0
            self.positions[order_ticket] = TradePosition(
                ticket=order_ticket,
                time=now,
                time_msc=now * 1000,
                time_update=now,
                time_update_msc=now * 1000,
                type=POSITION_TYPE_BUY if is_buy else POSITION_TYPE_SELL,
                magic=r.get("magic", 0),
                identifier=order_ticket,
                reason=DEAL_REASON_EXPERT,
                volume=volume,
                price_open=price,
                sl=r.get("sl", 0.0),
                tp=r.get("tp", 0.0),
                price_current=price,
                swap=0.0,
                profit=0.0,
                symbol=r["symbol"],
                comment=r.get("comment", ""),
                external_id="",
            )
        self.history_orders[order_ticket] = TradeOrder(
            ticket=order_ticket,
            time_setup=now,
            time_setup_msc=now * 1000,
            time_done=now,
            time_done_msc=now * 1000,
            time_expiration=0,
            type=r["type"],
            type_time=0,
            type_filling=r.get("type_filling", 0),
            state=ORDER_STATE_FILLED if b.fill_ratio >= 1 else ORDER_STATE_CANCELED,
            magic=r.get("magic", 0),
            position_id=position_id,
            position_by_id=0,
            reason=3,
            volume_initial=r["volume"],
            volume_current=round(r["volume"] - volume, 2),
            price_open=0.0,
            sl=r.get("sl", 0.0),
            tp=r.get("tp", 0.0),
            price_current=price,
            price_stoplimit=0.0,
            symbol=r["symbol"],
            comment=r.get("comment", ""),
            external_id="",
        )
        self.history_deals[deal_ticket] = TradeDeal(
            ticket=deal_ticket,
            order=order_ticket,
            time=now,
            time_msc=now * 1000,
            type=DEAL_TYPE_BUY if is_buy else DEAL_TYPE_SELL,
            entry=entry,
            magic=r.get("magic", 0),
            position_id=position_id,
            reason=DEAL_REASON_EXPERT,
            volume=volume,
            price=price,
            commission=-0.35 * volume * 10,
            swap=0.0,
            profit=profit,
            fee=0.0,
            symbol=r["symbol"],
            comment=r.get("comment", ""),
            external_id="",
        )
        return self._result(
            retcode,
            r,
            deal=deal_ticket,
            order=order_ticket,
            volume=volume,
            price=price,
            comment="Request executed",
        )

    def _pending(self, r: dict[str, Any]) -> OrderSendResult:
        is_buy = r["type"] in (ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_BUY_STOP)
        err = self._validate(r, r["price"], is_buy)
        if err is not None:
            return self._result(err, r)
        now = self.server_now()
        ticket = self._ticket()
        self.orders[ticket] = TradeOrder(
            ticket=ticket,
            time_setup=now,
            time_setup_msc=now * 1000,
            time_done=0,
            time_done_msc=0,
            time_expiration=0,
            type=r["type"],
            type_time=0,
            type_filling=r.get("type_filling", 0),
            state=ORDER_STATE_PLACED,
            magic=r.get("magic", 0),
            position_id=0,
            position_by_id=0,
            reason=3,
            volume_initial=r["volume"],
            volume_current=r["volume"],
            price_open=r["price"],
            sl=r.get("sl", 0.0),
            tp=r.get("tp", 0.0),
            price_current=r["price"],
            price_stoplimit=0.0,
            symbol=r["symbol"],
            comment=r.get("comment", ""),
            external_id="",
        )
        return self._result(
            TRADE_RETCODE_PLACED,
            r,
            order=ticket,
            volume=r["volume"],
            price=r["price"],
            comment="Request executed",
        )
