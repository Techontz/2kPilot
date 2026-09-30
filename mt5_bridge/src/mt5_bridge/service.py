"""Business operations. Each MT5 interaction is a synchronous unit of work executed
atomically on the single MT5 worker thread (see :mod:`mt5_bridge.terminal`)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar

from . import errors
from . import mapping as m
from .config import Settings
from .journal import DONE, Journal, JournalEntry
from .models import (
    ClosePositionRequest,
    ConnectRequest,
    ModifyOrderRequest,
    ModifyPositionRequest,
    OrderRequest,
)
from .terminal import (
    IPC_ERRORS,
    RES_E_AUTH_FAILED,
    RES_E_INVALID_PARAMS,
    Session,
    Terminal,
    TerminalTimeoutError,
)
from .timeutil import OffsetTracker, fmt_utc

log = logging.getLogger("mt5_bridge.service")

T = TypeVar("T")

BRIDGE_VERSION = "1.0.0"
MAX_CANDLES = 50_000
LOOKUP_DAYS = 7
OFFSET_META_KEY = "server_utc_offset"

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8
ORDER_TIME_GTC = 0

Response = tuple[int, dict[str, Any]]


class SendGuard:
    """Coordinates a trade unit of work with its (possibly timed-out) caller so a request
    that was abandoned before reaching ``order_send`` is never sent later."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sent = False
        self.abandoned = False

    def begin_send(self) -> None:
        with self._lock:
            if self.abandoned:
                raise errors.outcome_unknown("Request abandoned before it was sent")
            self.sent = True

    def abandon(self) -> bool:
        """Mark abandoned. Returns ``True`` if the request was certainly *not* sent."""
        with self._lock:
            self.abandoned = True
            return not self.sent


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


class BridgeService:
    def __init__(
        self, settings: Settings, terminal: Terminal, journal: Journal, clock: Callable[[], float]
    ) -> None:
        self.settings = settings
        self.terminal = terminal
        self.journal = journal
        self.clock = clock
        self.offsets = OffsetTracker(
            settings.fixed_offset_seconds,
            settings.broker_offset_refresh_seconds,
            clock,
            persist=self._persist_offset,
            initial=self._load_offset(),
        )
        self._trade_lock = asyncio.Lock()
        self._active: set[str] = set()

    # ------------------------------------------------------------------ infrastructure
    def _persist_offset(self, offset: int, measured_at: float) -> None:
        self.journal.set_meta(
            OFFSET_META_KEY, json.dumps({"offset": offset, "measured_at": measured_at})
        )

    def _load_offset(self) -> tuple[int, float] | None:
        raw = self.journal.get_meta(OFFSET_META_KEY)
        if raw is None:
            return None
        data = json.loads(raw)
        return int(data["offset"]), float(data["measured_at"])

    async def _read(self, fn: Callable[[Session], T]) -> T:
        try:
            return await self.terminal.run(fn, self.settings.read_timeout_seconds)
        except TerminalTimeoutError as exc:
            raise errors.timeout("Terminal read timed out") from exc

    async def _offset(self, required: bool) -> int:
        tracker = self.offsets
        if tracker.needs_measurement():

            def measure(s: Session) -> int | None:
                s.ensure_connected()
                return tracker.measure(s, self.settings.offset_symbols)

            try:
                await self.terminal.run(measure, self.settings.read_timeout_seconds)
            except (TerminalTimeoutError, errors.BridgeError) as exc:
                log.info("server offset measurement skipped", extra={"reason": repr(exc)})
        if tracker.offset is None:
            if required:
                raise errors.not_connected("server time offset unknown")
            log.warning("server time offset unknown; reporting server time as UTC")
            return 0
        return tracker.offset

    # ------------------------------------------------------------------ health/session
    async def health(self) -> dict[str, Any]:
        def fn(s: Session) -> dict[str, Any]:
            out: dict[str, Any] = {
                "initialized": False,
                "connected": False,
                "login": None,
                "server": None,
                "trade_allowed": False,
                "build": None,
            }
            try:
                s.ensure_initialized()
            except errors.BridgeError:
                return out
            ti = s.mt5.terminal_info()
            if ti is None:
                s.initialized = False
                return out
            out.update(
                initialized=True,
                connected=bool(ti.connected),
                trade_allowed=bool(ti.trade_allowed),
                build=int(ti.build),
            )
            ai = s.mt5.account_info()
            if ai is not None:
                out.update(login=str(ai.login), server=str(ai.server))
            return out

        try:
            terminal = await self.terminal.run(fn, self.settings.read_timeout_seconds)
        except (TerminalTimeoutError, errors.BridgeError):
            terminal = {
                "initialized": False,
                "connected": False,
                "login": None,
                "server": None,
                "trade_allowed": False,
                "build": None,
            }
        offset: int | None = None
        if terminal["connected"] or self.offsets.offset is not None:
            await self._offset(required=False)
            offset = self.offsets.offset
        return {
            "status": "ok",
            "bridge_version": BRIDGE_VERSION,
            "terminal": terminal,
            "server_utc_offset_seconds": offset,
            "time": fmt_utc(self.clock()),
        }

    async def connect(self, req: ConnectRequest) -> dict[str, Any]:
        login = int(req.login)
        password = req.password.get_secret_value()
        server = req.server
        path = req.terminal_path or self.settings.mt5_terminal_path
        timeout_ms = int(self.settings.connect_timeout_seconds * 1000)

        def fail(s: Session, what: str) -> errors.BridgeError:
            code, msg = s.last_error()
            if code in IPC_ERRORS:
                s.initialized = False
                return errors.not_connected(f"{what}: {msg}", str(code))
            return errors.broker_auth_failed(f"{what}: {msg}", str(code))

        def fn(s: Session) -> dict[str, Any]:
            mt5 = s.mt5
            if not s.initialized or mt5.terminal_info() is None:
                kwargs: dict[str, Any] = {
                    "login": login,
                    "password": password,
                    "server": server,
                    "timeout": timeout_ms,
                }
                if path:
                    kwargs["path"] = path
                if not mt5.initialize(**kwargs):
                    code, msg = s.last_error()
                    s.initialized = False
                    if code in (RES_E_AUTH_FAILED, RES_E_INVALID_PARAMS):
                        raise errors.broker_auth_failed(f"MT5 login failed: {msg}", str(code))
                    raise errors.not_connected(f"Terminal initialisation failed: {msg}", str(code))
                s.initialized = True
            elif not mt5.login(login, password=password, server=server, timeout=timeout_ms):
                raise fail(s, "MT5 login failed")
            ai = mt5.account_info()
            if ai is None:
                raise errors.not_connected("Terminal is not logged in after login")
            if int(ai.login) != login:
                raise errors.broker_auth_failed("Terminal is logged into a different account")
            return m.account_json(ai, mt5)

        try:
            result = await self.terminal.run(fn, self.settings.connect_timeout_seconds + 5)
        except TerminalTimeoutError as exc:
            raise errors.timeout("Terminal login timed out") from exc
        log.info("terminal logged in", extra={"login": req.login, "server": server})
        return result

    async def disconnect(self) -> dict[str, Any]:
        def fn(s: Session) -> None:
            if s.initialized:
                try:
                    s.mt5.shutdown()
                finally:
                    s.initialized = False

        if self.terminal.available:
            await self._read(fn)
        return {"ok": True}

    # ------------------------------------------------------------------ market data
    async def account(self) -> dict[str, Any]:
        def fn(s: Session) -> dict[str, Any]:
            return m.account_json(s.ensure_connected(), s.mt5)

        return await self._read(fn)

    async def symbols(self) -> list[dict[str, Any]]:
        def fn(s: Session) -> list[dict[str, Any]]:
            s.ensure_connected()
            infos = s.list_or_raise(s.mt5.symbols_get(), "symbols_get")
            out = [
                m.symbol_json(i)
                for i in infos
                if i.visible
                and int(i.trade_mode) != m.SYMBOL_TRADE_MODE_DISABLED
                and m.is_fx_or_metal(i)
            ]
            return sorted(out, key=lambda x: str(x["name"]))

        return await self._read(fn)

    async def quote(self, symbol: str) -> dict[str, Any]:
        offset = await self._offset(required=False)

        def fn(s: Session) -> dict[str, Any]:
            s.ensure_connected()
            info = s.ensure_symbol(symbol)
            tick = s.mt5.symbol_info_tick(symbol)
            if tick is None:
                code, _ = s.last_error()
                if code in IPC_ERRORS:
                    raise s.error_from_last("symbol_info_tick")
                raise errors.symbol_unavailable(f"No quote available for {symbol}")
            return m.quote_json(symbol, tick, int(info.digits), offset)

        return await self._read(fn)

    async def candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        if start >= end:
            raise errors.invalid_request("start must be before end")
        offset = await self._offset(required=True)
        start_s, end_s = int(start.timestamp()), int(end.timestamp())
        tf_seconds = m.TIMEFRAME_SECONDS[timeframe]
        now = self.clock()

        def fn(s: Session) -> list[dict[str, Any]]:
            s.ensure_connected()
            info = s.ensure_symbol(symbol)
            const_name, default = m.TIMEFRAME_CONST[timeframe]
            tf = m.const(s.mt5, const_name, default)
            rates = s.mt5.copy_rates_range(symbol, tf, _dt(start_s + offset), _dt(end_s + offset))
            rows = s.list_or_raise(rates, "copy_rates_range")
            digits = int(info.digits)
            out: list[dict[str, Any]] = []
            for row in rows:
                t_utc = int(row["time"]) - offset
                if t_utc < start_s or t_utc >= end_s:
                    continue
                if t_utc + tf_seconds > now:  # still forming
                    continue
                out.append(m.candle_json(row, digits, offset))
            out.sort(key=lambda c: str(c["time"]))
            return out[:MAX_CANDLES]

        return await self._read(fn)

    # ------------------------------------------------------------------ trading state
    @staticmethod
    def _digits_cache(s: Session) -> Callable[[str], int | None]:
        cache: dict[str, int | None] = {}

        def digits(symbol: str) -> int | None:
            if symbol not in cache:
                info = s.mt5.symbol_info(symbol)
                cache[symbol] = int(info.digits) if info is not None else None
            return cache[symbol]

        return digits

    @staticmethod
    def _money_places(ai: Any) -> int:
        return int(getattr(ai, "currency_digits", 2) or 2)

    async def positions(self) -> list[dict[str, Any]]:
        offset = await self._offset(required=False)

        def fn(s: Session) -> list[dict[str, Any]]:
            ai = s.ensure_connected()
            digits = self._digits_cache(s)
            out = []
            for p in s.list_or_raise(s.mt5.positions_get(), "positions_get"):
                coid = m.parse_client_order_id(p.comment) or self._opening_deal_coid(s, p)
                out.append(
                    m.position_json(p, digits(p.symbol), offset, coid, self._money_places(ai))
                )
            return out

        return await self._read(fn)

    @staticmethod
    def _opening_deal_coid(s: Session, p: Any) -> str | None:
        ident = int(getattr(p, "identifier", 0) or p.ticket)
        deals = s.mt5.history_deals_get(position=ident) or ()
        for d in deals:
            if int(d.entry) == m.DEAL_ENTRY_IN:
                return m.parse_client_order_id(d.comment)
        return None

    async def orders(self) -> list[dict[str, Any]]:
        offset = await self._offset(required=False)

        def fn(s: Session) -> list[dict[str, Any]]:
            s.ensure_connected()
            digits = self._digits_cache(s)
            return [
                m.order_json(o, digits(o.symbol), offset)
                for o in s.list_or_raise(s.mt5.orders_get(), "orders_get")
            ]

        return await self._read(fn)

    async def deals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if start >= end:
            raise errors.invalid_request("start must be before end")
        offset = await self._offset(required=True)
        start_s, end_s = int(start.timestamp()), int(end.timestamp())

        def fn(s: Session) -> list[dict[str, Any]]:
            ai = s.ensure_connected()
            digits = self._digits_cache(s)
            raw = s.mt5.history_deals_get(_dt(start_s + offset), _dt(end_s + offset))
            rows = [
                d
                for d in s.list_or_raise(raw, "history_deals_get")
                if int(d.type) in (m.DEAL_TYPE_BUY, m.DEAL_TYPE_SELL)
                and start_s <= int(d.time) - offset < end_s
            ]
            rows.sort(key=lambda d: (int(getattr(d, "time_msc", 0) or d.time), int(d.ticket)))
            return [m.deal_json(d, digits(d.symbol), offset, self._money_places(ai)) for d in rows]

        return await self._read(fn)

    # ------------------------------------------------------------------ reconciliation
    def _find_in_mt5(self, s: Session, coid: str) -> dict[str, Any] | None:
        """Search pending orders, order history, positions and deal history by comment."""
        s.ensure_connected()
        mt5 = s.mt5
        digits = self._digits_cache(s)

        def match(x: Any) -> bool:
            return m.parse_client_order_id(getattr(x, "comment", "")) == coid

        for o in s.list_or_raise(mt5.orders_get(), "orders_get"):
            if match(o):
                filled = max(float(o.volume_initial) - float(o.volume_current), 0.0)
                return m.order_result(
                    coid,
                    "PENDING",
                    o.ticket,
                    getattr(o, "position_id", 0),
                    filled,
                    None,
                    digits(o.symbol),
                    None,
                    "Recovered from MT5 pending orders",
                )

        now = self.clock()
        date_from = _dt(now - (LOOKUP_DAYS + 1) * 86400)
        date_to = _dt(now + 86400)
        hist = s.list_or_raise(mt5.history_orders_get(date_from, date_to), "history_orders_get")
        for o in hist:
            if match(o):
                return self._result_from_history_order(s, coid, o, digits(o.symbol))

        for p in s.list_or_raise(mt5.positions_get(), "positions_get"):
            if match(p):
                ident = int(getattr(p, "identifier", 0) or p.ticket)
                return m.order_result(
                    coid,
                    "FILLED",
                    ident,
                    p.ticket,
                    p.volume,
                    p.price_open,
                    digits(p.symbol),
                    None,
                    "Recovered from MT5 positions",
                )

        deals = [
            d
            for d in s.list_or_raise(mt5.history_deals_get(date_from, date_to), "history_deals_get")
            if match(d)
        ]
        if deals:
            vol, price = m.weighted_price(deals)
            d0 = deals[0]
            return m.order_result(
                coid,
                "FILLED",
                d0.order,
                d0.position_id,
                vol,
                price,
                digits(d0.symbol),
                None,
                "Recovered from MT5 deal history",
            )
        return None

    @staticmethod
    def _result_from_history_order(
        s: Session, coid: str, o: Any, digits: int | None
    ) -> dict[str, Any]:
        deals = list(s.mt5.history_deals_get(ticket=int(o.ticket)) or ())
        if deals:
            filled, price = m.weighted_price(deals)
            position_id = int(deals[0].position_id) or int(getattr(o, "position_id", 0))
        else:
            filled = max(float(o.volume_initial) - float(o.volume_current), 0.0)
            price = float(getattr(o, "price_current", 0.0) or 0.0) if filled else 0.0
            position_id = int(getattr(o, "position_id", 0))
        initial = float(o.volume_initial)
        state = int(o.state)
        if state in (
            m.ORDER_STATE_FILLED,
            m.ORDER_STATE_PARTIAL,
            m.ORDER_STATE_CANCELED,
            m.ORDER_STATE_EXPIRED,
        ):
            if filled <= 0:
                status = (
                    "CANCELLED"
                    if state in (m.ORDER_STATE_CANCELED, m.ORDER_STATE_EXPIRED)
                    else "FILLED"
                )
            elif filled + 1e-9 < initial:
                status = "PARTIALLY_FILLED"
            else:
                status = "FILLED"
        elif state == m.ORDER_STATE_REJECTED:
            status = "REJECTED"
        else:
            status = "PENDING"
        return m.order_result(
            coid,
            status,
            o.ticket,
            position_id or None,
            filled,
            price or None,
            digits,
            None,
            "Recovered from MT5 order history",
        )

    @staticmethod
    def _result_from_entry(entry: JournalEntry) -> dict[str, Any]:
        if entry.response is None:
            raise errors.internal("Journal entry has no stored response")
        if entry.status_code == 200:
            return entry.response
        err = entry.response.get("error", {})
        return m.order_result(
            entry.client_order_id,
            "REJECTED",
            None,
            None,
            0,
            None,
            None,
            err.get("broker_code"),
            err.get("message"),
        )

    async def lookup(self, coid: str) -> dict[str, Any]:
        entry = self.journal.get(coid)
        if entry is not None and entry.state == DONE:
            return self._result_from_entry(entry)
        try:
            found = await self._read(lambda s: self._find_in_mt5(s, coid))
        except errors.BridgeError as exc:
            if entry is not None:
                raise errors.outcome_unknown(
                    f"Outcome of {coid} unknown and MT5 lookup failed: {exc.message}"
                ) from exc
            raise
        if found is not None:
            if entry is not None and coid not in self._active:
                self.journal.mark_done(coid, 200, found)
            return found
        if entry is not None:
            raise errors.outcome_unknown(f"Outcome of {coid} is still unknown")
        raise errors.not_found(f"No order with client_order_id {coid}")

    # ------------------------------------------------------------------ order changes
    async def submit_order(self, req: OrderRequest) -> Response:
        request = req.model_dump(mode="json")

        def sender(s: Session, guard: SendGuard) -> dict[str, Any]:
            return self._send_new_order(s, req, guard)

        return await self._idempotent(req.client_order_id, "order", req.symbol, request, sender)

    async def close_position(self, position_id: str, req: ClosePositionRequest) -> Response:
        request = {"position_id": position_id, **req.model_dump(mode="json")}

        def sender(s: Session, guard: SendGuard) -> dict[str, Any]:
            return self._send_close(s, int(position_id), req, guard)

        return await self._idempotent(
            req.client_order_id, "close", f"position:{position_id}", request, sender
        )

    async def _idempotent(
        self,
        coid: str,
        kind: str,
        target: str,
        request: dict[str, Any],
        sender: Callable[[Session, SendGuard], dict[str, Any]],
    ) -> Response:
        async with self._trade_lock:
            entry = self.journal.get(coid)
            if entry is not None:
                return await self._replay(entry, kind, target)

            self.journal.insert_in_flight(coid, kind, target, request)
            guard = SendGuard()
            self._active.add(coid)
            try:
                result = await self.terminal.run(
                    lambda s: sender(s, guard), self.settings.trade_timeout_seconds
                )
            except TerminalTimeoutError as exc:
                if guard.abandon():
                    self.journal.delete(coid)
                    raise errors.outcome_unknown(
                        "Trade request timed out before it was sent to MT5"
                    ) from exc
                self.journal.mark_unknown(coid)
                log.error("trade outcome unknown (timeout)", extra={"client_order_id": coid})
                raise errors.outcome_unknown("Trade request timed out") from exc
            except errors.BridgeError as exc:
                if not guard.sent:
                    self.journal.delete(coid)
                elif exc.code == "outcome_unknown":
                    self.journal.mark_unknown(coid)
                    log.error(
                        "trade outcome unknown",
                        extra={"client_order_id": coid, "reason": exc.message},
                    )
                else:
                    self.journal.mark_done(coid, exc.status_code, exc.body())
                raise
            except Exception as exc:
                if not guard.sent:
                    self.journal.delete(coid)
                    raise
                self.journal.mark_unknown(coid)
                log.exception("trade outcome unknown (exception)", extra={"client_order_id": coid})
                raise errors.outcome_unknown("Unexpected error while sending trade") from exc
            finally:
                self._active.discard(coid)
            self.journal.mark_done(coid, 200, result)
            log.info("trade done", extra={"client_order_id": coid, "status": result["status"]})
            return 200, result

    async def _replay(self, entry: JournalEntry, kind: str, target: str) -> Response:
        if entry.kind != kind or entry.target != target:
            raise errors.invalid_request("client_order_id was already used for a different request")
        if entry.state == DONE:
            if entry.status_code is None or entry.response is None:
                raise errors.internal("Journal entry has no stored response")
            return entry.status_code, entry.response
        coid = entry.client_order_id
        try:
            found = await self._read(lambda s: self._find_in_mt5(s, coid))
        except errors.BridgeError as exc:
            raise errors.outcome_unknown(
                f"Previous attempt for {coid} has an unknown outcome and MT5 lookup failed: "
                f"{exc.message}"
            ) from exc
        if found is None:
            raise errors.outcome_unknown(
                f"Previous attempt for {coid} has an unknown outcome; not resending"
            )
        self.journal.mark_done(coid, 200, found)
        return 200, found

    # -- trade units of work (run on the MT5 thread) ------------------------------------
    def _tick(self, s: Session, symbol: str) -> Any:
        tick = s.mt5.symbol_info_tick(symbol)
        if tick is None or not tick.bid or not tick.ask:
            code, _ = s.last_error()
            if code in IPC_ERRORS:
                raise s.error_from_last("symbol_info_tick")
            raise errors.market_closed(f"No current price for {symbol}")
        return tick

    @staticmethod
    def _send(s: Session, request: dict[str, Any], guard: SendGuard) -> Any:
        guard.begin_send()
        try:
            result = s.mt5.order_send(request)
        except Exception as exc:
            raise errors.outcome_unknown(f"order_send raised {type(exc).__name__}") from exc
        if result is None:
            code, msg = s.last_error()
            if code in IPC_ERRORS:
                s.initialized = False
            raise errors.outcome_unknown(f"order_send returned no result: {msg}", str(code))
        retcode = int(result.retcode)
        err = m.retcode_error(retcode, getattr(result, "comment", ""))
        if err is not None:
            raise err
        return result

    @staticmethod
    def _position_for_order(s: Session, order_ticket: int) -> int:
        try:
            for d in s.mt5.history_deals_get(ticket=order_ticket) or ():
                if int(d.position_id):
                    return int(d.position_id)
        except Exception:
            log.warning("position lookup after fill failed", exc_info=True)
        return order_ticket  # MT5: the position id equals the opening order ticket

    def _send_new_order(self, s: Session, req: OrderRequest, guard: SendGuard) -> dict[str, Any]:
        mt5 = s.mt5
        s.ensure_connected()
        info = s.ensure_symbol(req.symbol)
        digits = int(info.digits)
        otype = m.mt5_order_type(req.side, req.order_type)
        request: dict[str, Any] = {
            "symbol": req.symbol,
            "volume": float(req.volume),
            "type": m.const(mt5, _ORDER_TYPE_NAMES[otype], otype),
            "sl": _price(req.stop_loss, digits),
            "tp": _price(req.take_profit, digits),
            "deviation": int(req.max_slippage_points),
            "magic": int(self.settings.mt5_magic),
            "comment": m.build_comment(req.client_order_id, req.comment),
            "type_time": m.const(mt5, "ORDER_TIME_GTC", ORDER_TIME_GTC),
            "type_filling": m.select_filling(int(info.filling_mode), mt5),
        }
        if req.order_type == "MARKET":
            tick = self._tick(s, req.symbol)
            request["action"] = m.const(mt5, "TRADE_ACTION_DEAL", TRADE_ACTION_DEAL)
            request["price"] = float(tick.ask if req.side == "BUY" else tick.bid)
        else:
            request["action"] = m.const(mt5, "TRADE_ACTION_PENDING", TRADE_ACTION_PENDING)
            request["price"] = _price(req.price, digits)

        result = self._send(s, request, guard)
        retcode = int(result.retcode)
        status = m.retcode_status(retcode)
        order_ticket = int(result.order)
        msg = m.retcode_message(retcode, result.comment)
        if status == "PENDING":
            return m.order_result(
                req.client_order_id, status, order_ticket, None, 0, None, digits, retcode, msg
            )
        position_id = self._position_for_order(s, order_ticket)
        return m.order_result(
            req.client_order_id,
            status,
            order_ticket,
            position_id,
            result.volume,
            result.price,
            digits,
            retcode,
            msg,
        )

    def _send_close(
        self, s: Session, position_id: int, req: ClosePositionRequest, guard: SendGuard
    ) -> dict[str, Any]:
        mt5 = s.mt5
        s.ensure_connected()
        positions = s.list_or_raise(mt5.positions_get(ticket=position_id), "positions_get")
        if not positions:
            raise errors.not_found(f"Position {position_id} not found")
        p = positions[0]
        info = s.ensure_symbol(p.symbol)
        digits = int(info.digits)
        volume = float(req.volume) if req.volume is not None else float(p.volume)
        if volume > float(p.volume) + 1e-9:
            raise errors.invalid_request("volume exceeds the position volume")
        tick = self._tick(s, p.symbol)
        closing_buy = int(p.type) == m.POSITION_TYPE_BUY
        otype = m.ORDER_TYPE_SELL if closing_buy else m.ORDER_TYPE_BUY
        deviation = (
            req.max_slippage_points
            if req.max_slippage_points is not None
            else self.settings.mt5_default_deviation_points
        )
        request = {
            "action": m.const(mt5, "TRADE_ACTION_DEAL", TRADE_ACTION_DEAL),
            "position": int(p.ticket),
            "symbol": p.symbol,
            "volume": volume,
            "type": m.const(mt5, _ORDER_TYPE_NAMES[otype], otype),
            "price": float(tick.bid if closing_buy else tick.ask),
            "deviation": int(deviation),
            "magic": int(self.settings.mt5_magic),
            "comment": m.build_comment(req.client_order_id),
            "type_time": m.const(mt5, "ORDER_TIME_GTC", ORDER_TIME_GTC),
            "type_filling": m.select_filling(int(info.filling_mode), mt5),
        }
        result = self._send(s, request, guard)
        retcode = int(result.retcode)
        status = m.retcode_status(retcode)
        return m.order_result(
            req.client_order_id,
            status,
            int(result.order),
            p.ticket,
            result.volume if status != "PENDING" else 0,
            result.price if status != "PENDING" else None,
            digits,
            retcode,
            m.retcode_message(retcode, result.comment),
        )

    async def _trade(self, fn: Callable[[Session, SendGuard], dict[str, Any]]) -> dict[str, Any]:
        """Order-changing request without a client_order_id (modify/cancel)."""
        async with self._trade_lock:
            guard = SendGuard()
            try:
                return await self.terminal.run(
                    lambda s: fn(s, guard), self.settings.trade_timeout_seconds
                )
            except TerminalTimeoutError as exc:
                guard.abandon()
                raise errors.outcome_unknown("Trade request timed out") from exc
            except errors.BridgeError:
                raise
            except Exception as exc:
                if guard.sent:
                    raise errors.outcome_unknown("Unexpected error while sending trade") from exc
                raise

    async def modify_order(self, order_id: str, req: ModifyOrderRequest) -> dict[str, Any]:
        fields = req.model_fields_set

        def fn(s: Session, guard: SendGuard) -> dict[str, Any]:
            mt5 = s.mt5
            s.ensure_connected()
            orders = s.list_or_raise(mt5.orders_get(ticket=int(order_id)), "orders_get")
            if not orders:
                raise errors.not_found(f"Order {order_id} not found")
            o = orders[0]
            info = mt5.symbol_info(o.symbol)
            digits = int(info.digits) if info is not None else None
            request = {
                "action": m.const(mt5, "TRADE_ACTION_MODIFY", TRADE_ACTION_MODIFY),
                "order": int(o.ticket),
                "symbol": o.symbol,
                "price": _price(req.price, digits)
                if req.price is not None
                else float(o.price_open),
                "sl": _price(req.stop_loss, digits) if "stop_loss" in fields else float(o.sl),
                "tp": _price(req.take_profit, digits) if "take_profit" in fields else float(o.tp),
                "type_time": int(getattr(o, "type_time", ORDER_TIME_GTC)),
                "expiration": int(getattr(o, "time_expiration", 0)),
            }
            result = self._send(s, request, guard)
            retcode = int(result.retcode)
            return m.order_result(
                m.parse_client_order_id(o.comment),
                "PENDING",
                o.ticket,
                None,
                0,
                None,
                digits,
                retcode,
                m.retcode_message(retcode, result.comment),
            )

        return await self._trade(fn)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        def fn(s: Session, guard: SendGuard) -> dict[str, Any]:
            mt5 = s.mt5
            s.ensure_connected()
            orders = s.list_or_raise(mt5.orders_get(ticket=int(order_id)), "orders_get")
            if not orders:
                raise errors.not_found(f"Order {order_id} not found")
            o = orders[0]
            request = {
                "action": m.const(mt5, "TRADE_ACTION_REMOVE", TRADE_ACTION_REMOVE),
                "order": int(o.ticket),
            }
            result = self._send(s, request, guard)
            retcode = int(result.retcode)
            filled = max(float(o.volume_initial) - float(o.volume_current), 0.0)
            return m.order_result(
                m.parse_client_order_id(o.comment),
                "CANCELLED",
                o.ticket,
                None,
                filled,
                None,
                None,
                retcode,
                m.retcode_message(retcode, result.comment),
            )

        return await self._trade(fn)

    async def modify_position(self, position_id: str, req: ModifyPositionRequest) -> dict[str, Any]:
        fields = req.model_fields_set

        def fn(s: Session, guard: SendGuard) -> dict[str, Any]:
            mt5 = s.mt5
            s.ensure_connected()
            positions = s.list_or_raise(mt5.positions_get(ticket=int(position_id)), "positions_get")
            if not positions:
                raise errors.not_found(f"Position {position_id} not found")
            p = positions[0]
            info = mt5.symbol_info(p.symbol)
            digits = int(info.digits) if info is not None else None
            request = {
                "action": m.const(mt5, "TRADE_ACTION_SLTP", TRADE_ACTION_SLTP),
                "position": int(p.ticket),
                "symbol": p.symbol,
                "sl": _price(req.stop_loss, digits) if "stop_loss" in fields else float(p.sl),
                "tp": _price(req.take_profit, digits) if "take_profit" in fields else float(p.tp),
                "magic": int(self.settings.mt5_magic),
            }
            result = self._send(s, request, guard)
            retcode = int(result.retcode)
            coid = m.parse_client_order_id(p.comment) or self._opening_deal_coid(s, p)
            ident = int(getattr(p, "identifier", 0) or p.ticket)
            return m.order_result(
                coid,
                "FILLED",
                ident,
                p.ticket,
                p.volume,
                p.price_open,
                digits,
                retcode,
                m.retcode_message(retcode, result.comment),
            )

        return await self._trade(fn)


_ORDER_TYPE_NAMES = {
    m.ORDER_TYPE_BUY: "ORDER_TYPE_BUY",
    m.ORDER_TYPE_SELL: "ORDER_TYPE_SELL",
    m.ORDER_TYPE_BUY_LIMIT: "ORDER_TYPE_BUY_LIMIT",
    m.ORDER_TYPE_SELL_LIMIT: "ORDER_TYPE_SELL_LIMIT",
    m.ORDER_TYPE_BUY_STOP: "ORDER_TYPE_BUY_STOP",
    m.ORDER_TYPE_SELL_STOP: "ORDER_TYPE_SELL_STOP",
}


def _price(value: Decimal | None, digits: int | None) -> float:
    if value is None:
        return 0.0
    return round(float(value), digits) if digits is not None else float(value)
