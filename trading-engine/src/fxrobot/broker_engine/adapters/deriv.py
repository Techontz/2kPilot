"""Deriv adapter — Options/Multipliers API (developers.deriv.com, 2026 API).

How Deriv maps onto the 2kFX broker contract
--------------------------------------------
Deriv trades forex, synthetic indices, commodities, indices and crypto through
*multiplier* contracts (MULTUP = buy, MULTDOWN = sell). A multiplier position
behaves like a leveraged position:

    profit = stake × multiplier × (price change ÷ entry price)  − commission

2kFX keeps one vocabulary for every broker, so this adapter translates:

* volume  — expressed in **lots**, with MetaTrader-style contract sizes so a
  risk profile ("max 1.0 lots") means the same on every broker:
  forex 1 lot = 100,000 units of the base currency; gold/platinum 100 oz;
  silver 5,000 oz; indices, synthetics and crypto 1 unit.
  lots × contract size × price (in account currency) = notional = stake × multiplier.
  The stake actually paid is `notional ÷ multiplier`, rounded down to cents.
* stop loss / take profit — 2kFX uses PRICES; Deriv wants MONEY AMOUNTS.
  amount = notional × |entry − level| ÷ entry. Deriv caps the stop-loss
  amount at the stake (a stop further away is refused before sending).
* pending orders — not offered by Deriv: refused, and advertised as
  unsupported through `capabilities`.
* idempotency — Deriv does not store a client order id. Every order intent is
  remembered, and after a timeout/restart reconciliation matches contracts by
  symbol, direction and purchase time (`OrderHint`). An order whose outcome is
  uncertain is never re-sent.

The multiplier used for each symbol is the LOWEST the broker allows (widest
room for a stop loss, least leverage) unless the connection settings choose
another value from the broker's allowed list.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from typing import Any

from fxrobot.broker_engine.adapters.deriv_client import (
    Connector,
    DerivAccount,
    DerivApiError,
    DerivRest,
    DerivSocket,
    default_connector,
)
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerTimeoutError,
    InsufficientMarginError,
    InvalidBrokerResponseError,
    MarketClosedError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.models import (
    AccountInfo,
    BrokerCapabilities,
    BrokerHealth,
    Candle,
    Deal,
    DealEntry,
    Order,
    OrderHint,
    OrderModification,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    SymbolInfo,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.market_data.conversion import conversion_rate

CENT = Decimal("0.01")
SYMBOLS_TTL = 600.0  # seconds
SPEC_TTL = 600.0
QUOTE_FRESH = 10.0
PORTFOLIO_REFRESH = 30.0
MATCH_BEFORE = timedelta(seconds=10)  # clock skew allowance when matching contracts
MATCH_AFTER = timedelta(minutes=3)

CATEGORIES = {
    "forex": "forex",
    "synthetic_index": "synthetic",
    "indices": "indices",
    "commodities": "commodities",
    "cryptocurrency": "crypto",
    "stocks": "stocks",
}
GRANULARITIES = {60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400}


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _map_api_error(exc: DerivApiError) -> OrderRejectedError:
    code = exc.subcode or exc.deriv_code
    if code == "MarketIsClosed" or exc.deriv_code == "MarketIsClosed":
        return MarketClosedError(str(exc), broker_code=code)
    if code in ("InsufficientBalance", "InsufficientFunds"):
        return InsufficientMarginError(str(exc), broker_code=code)
    return OrderRejectedError(str(exc), broker_code=code)


class DerivAdapter(BrokerAdapter):
    connector_id = "deriv"
    capabilities = BrokerCapabilities(
        market_orders=True,
        pending_orders=False,
        modify_position=True,
        partial_close=False,
        historical_candles=True,
        trade_history=True,
        client_order_ids=False,
        volume_unit="lots",
        notes=(
            "Trades are Deriv multiplier contracts (MULTUP = buy, MULTDOWN = sell).",
            "Volume is in lots (forex 1 lot = 100,000 units); stake = notional ÷ multiplier.",
            "Deriv limits the stop-loss amount to the stake; there are no pending orders.",
        ),
    )

    def __init__(
        self,
        *,
        token: str,
        account_id: str,
        app_id: str = "",
        token_kind: str = "pat",  # noqa: S107 (a kind, not a secret)
        multiplier: int | None = None,
        rest: DerivRest | None = None,
        connector: Connector = default_connector,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not account_id:
            raise ValueError("A Deriv account id is required")
        self.account_id = account_id
        self._rest = rest or DerivRest(token=token, app_id=app_id, token_kind=token_kind)
        self._connector = connector
        self._clock = clock
        self._preferred_multiplier = multiplier
        self._socket: DerivSocket | None = None
        self._account: DerivAccount | None = None
        self._lock = threading.RLock()
        # caches (filled from responses and streams)
        self._active: dict[str, dict[str, Any]] = {}
        self._active_at = 0.0
        self._specs: dict[str, tuple[SymbolInfo, int, float]] = {}  # name -> (info, mult, at)
        self._quotes: dict[str, Quote] = {}
        self._tick_subscribed: set[str] = set()
        self._contracts: dict[str, dict[str, Any]] = {}  # contract_id -> latest POC
        self._sold: dict[str, dict[str, Any]] = {}  # immutable details of closed contracts
        self._units: dict[str, Decimal] = {}  # contract_id -> volume in lots (stable)
        self._balance: Decimal | None = None
        self._portfolio_at = 0.0
        # idempotency bookkeeping
        self._client_by_contract: dict[str, str] = {}
        self._contract_by_client: dict[str, str] = {}

    # ── connection ───────────────────────────────────────────────────────
    def list_accounts(self) -> list[DerivAccount]:
        """All Options accounts the token can reach (used by the Add Broker wizard)."""
        return self._rest.accounts()

    def connect(self) -> AccountInfo:
        with self._lock:
            if self.is_connected:
                return self.get_account()
            account = next(
                (a for a in self._rest.accounts() if a.account_id == self.account_id), None
            )
            if account is None:
                raise BrokerAuthError(
                    f"Deriv account {self.account_id} is not available to this token"
                )
            self._account = account
            url = self._rest.otp_url(self.account_id)  # single-use, valid 120 s
            socket = DerivSocket(url, connector=self._connector)
            socket.on("tick", self._on_tick)
            socket.on("balance", self._on_balance)
            socket.on("proposal_open_contract", self._on_contract)
            self._socket = socket
            self._tick_subscribed.clear()
            try:
                reply = socket.request({"balance": 1, "subscribe": 1})
                self._on_balance(reply)
                self._refresh_portfolio(force=True)
                with contextlib.suppress(DerivApiError):  # stream of all open contracts
                    socket.request({"proposal_open_contract": 1, "subscribe": 1})
            except BrokerError:
                socket.close()
                self._socket = None
                raise
            return self.get_account()

    def disconnect(self) -> None:
        with self._lock:
            if self._socket is not None:
                self._socket.close()
            self._socket = None

    @property
    def is_connected(self) -> bool:
        return self._socket is not None and self._socket.is_open

    def health(self) -> BrokerHealth:
        if not self.is_connected:
            return BrokerHealth(False, "Not connected to Deriv")
        started = time.monotonic()
        try:
            self._ws().request({"ping": 1}, timeout=10)
        except BrokerError as exc:
            return BrokerHealth(False, f"Deriv did not answer: {exc}")
        return BrokerHealth(True, "Connected", (time.monotonic() - started) * 1000)

    def now(self) -> datetime:
        return self._clock()

    def _ws(self) -> DerivSocket:
        socket = self._socket
        if socket is None or not socket.is_open:
            raise BrokerConnectionError("Not connected to Deriv")
        return socket

    # ── streams ──────────────────────────────────────────────────────────
    def _on_tick(self, message: dict[str, Any]) -> None:
        tick = message.get("tick")
        if not isinstance(tick, dict):
            return
        quote_price = _dec(tick.get("quote"))
        when = _epoch(tick.get("epoch"))
        symbol = str(tick.get("symbol") or "")
        if quote_price is None or when is None or not symbol:
            return
        bid = _dec(tick.get("bid")) or quote_price
        ask = _dec(tick.get("ask")) or quote_price
        self._quotes[symbol] = Quote(symbol, bid, ask, when)

    def _on_balance(self, message: dict[str, Any]) -> None:
        data = message.get("balance")
        if isinstance(data, dict):
            self._balance = _dec(data.get("balance"))

    def _on_contract(self, message: dict[str, Any]) -> None:
        poc = message.get("proposal_open_contract")
        if not isinstance(poc, dict) or poc.get("contract_id") is None:
            return
        cid = str(poc["contract_id"])
        if poc.get("is_sold"):
            self._contracts.pop(cid, None)
            self._sold[cid] = poc
        else:
            self._contracts[cid] = poc

    # ── account ──────────────────────────────────────────────────────────
    def get_account(self) -> AccountInfo:
        if self._account is None:
            raise BrokerConnectionError("Not connected to Deriv")
        account = self._account
        if self.is_connected:  # cheap (100/min budget); the stream also keeps it fresh
            with contextlib.suppress(BrokerTimeoutError):
                self._on_balance(self._ws().request({"balance": 1}))
        balance = self._balance if self._balance is not None else _dec(account.balance)
        if balance is None:
            raise InvalidBrokerResponseError("Deriv did not report a balance")
        open_value = sum(
            (_dec(c.get("bid_price")) or Decimal(0) for c in self._contracts.values()),
            Decimal(0),
        )
        environment = {
            "demo": AccountEnvironment.DEMO,
            "real": AccountEnvironment.LIVE,
        }.get(account.account_type, AccountEnvironment.UNKNOWN)
        return AccountInfo(
            account_id=account.account_id,
            name=f"Deriv {account.account_type.upper()} {account.account_id}",
            server=f"Deriv Options ({account.account_type})",
            currency=account.currency,
            environment=environment,
            balance=balance,
            # The stake of an open multiplier is already debited; its current
            # value (bid price) is part of equity.
            equity=balance + open_value,
            trade_allowed=account.status == "active",
        )

    # ── symbols ──────────────────────────────────────────────────────────
    def _active_symbols(self) -> dict[str, dict[str, Any]]:
        if self._active and time.monotonic() - self._active_at < SYMBOLS_TTL:
            return self._active
        reply = self._ws().request(
            {"active_symbols": "brief", "contract_type": ["MULTUP", "MULTDOWN"]}
        )
        items = reply.get("active_symbols")
        if not isinstance(items, list):
            raise InvalidBrokerResponseError("Deriv active_symbols response is malformed")
        self._active = {
            str(i["underlying_symbol"]): i
            for i in items
            if isinstance(i, dict) and i.get("underlying_symbol")
        }
        self._active_at = time.monotonic()
        return self._active

    def resolve(self, name: str) -> str:
        """Accept broker names (frxEURUSD) and canonical names (EURUSD)."""
        active = self._active_symbols()
        if name in active:
            return name
        if f"frx{name}" in active:
            return f"frx{name}"
        raise SymbolUnavailableError(f"Symbol {name} is not available on Deriv")

    @staticmethod
    def _currencies(name: str, market: str) -> tuple[str, str, str]:
        """(canonical, base, quote) for a Deriv symbol."""
        if name.startswith("frx") and len(name) == 9:
            pair = name[3:]
            return pair, pair[:3], pair[3:]
        if name.startswith("cry") and name.endswith("USD"):
            return name[3:], name[3:-3], "USD"
        return name, name, "USD"  # indices & synthetics are quoted in USD

    def _base_info(self, item: dict[str, Any]) -> SymbolInfo:
        name = str(item["underlying_symbol"])
        canonical, base, quote = self._currencies(name, str(item.get("market", "")))
        pip = _dec(item.get("pip_size")) or Decimal("0.01")
        digits = max(0, -pip.normalize().as_tuple().exponent)  # type: ignore[operator]
        open_now = bool(item.get("exchange_is_open")) and not bool(item.get("is_trading_suspended"))
        return SymbolInfo(
            name=name,
            description=str(item.get("underlying_symbol_name") or name),
            base_currency=base,
            quote_currency=quote,
            digits=digits,
            point=pip,
            contract_size=contract_size_of(name),
            volume_min=Decimal("0.01"),
            volume_max=Decimal("1000000"),
            volume_step=Decimal("0.01"),
            trade_allowed=not bool(item.get("is_trading_suspended")),
            canonical=canonical,
            category=CATEGORIES.get(str(item.get("market")), "other"),
            market_open=open_now,
        )

    def get_symbols(self) -> list[SymbolInfo]:
        """Instrument list (volume limits are refined per symbol by get_symbol)."""
        return [self._base_info(i) for i in self._active_symbols().values()]

    def multiplier_for(self, name: str) -> int:
        self.get_symbol(name)
        return self._specs[self.resolve(name)][1]

    def get_symbol(self, name: str) -> SymbolInfo:
        """Full specification: allowed multiplier and stake limits → volume limits."""
        broker_name = self.resolve(name)
        cached = self._specs.get(broker_name)
        if cached and time.monotonic() - cached[2] < SPEC_TTL:
            fresh = self._base_info(self._active[broker_name])
            return _with_status(cached[0], fresh.market_open, fresh.trade_allowed)
        base = self._base_info(self._active[broker_name])
        reply = self._ws().request({"contracts_for": broker_name})
        offered = (reply.get("contracts_for") or {}).get("available") or []
        ranges = [
            [int(m) for m in (c.get("multiplier_range") or [])]
            for c in offered
            if isinstance(c, dict) and c.get("contract_category") == "multiplier"
        ]
        allowed = sorted({m for r in ranges for m in r})
        if not allowed:
            raise SymbolUnavailableError(f"Deriv offers no multiplier contracts on {name}")
        multiplier = (
            self._preferred_multiplier if self._preferred_multiplier in allowed else allowed[0]
        )
        stake_min, stake_max = Decimal(1), Decimal(1000)
        with contextlib.suppress(DerivApiError):
            proposal = self._proposal(broker_name, Side.BUY, Decimal(10), multiplier, None, None)
            params = proposal.get("validation_params") or {}
            stake = params.get("stake") or {}
            stake_min = _dec(stake.get("min")) or stake_min
            stake_max = _dec(stake.get("max")) or stake_max
        rate = self._price_in_account(base, broker_name)
        per_lot = rate * base.contract_size  # account-currency value of 1 lot
        step = Decimal("0.01") if per_lot <= 1_000_000 else Decimal("0.0001")
        if per_lot > 0:
            vmin = (stake_min * multiplier / per_lot / step).to_integral_value(ROUND_UP) * step
            vmax = (stake_max * multiplier / per_lot / step).to_integral_value(ROUND_DOWN) * step
        else:
            vmin, vmax = step, step
        info = SymbolInfo(
            name=base.name,
            description=f"{base.description} (multiplier ×{multiplier})",
            base_currency=base.base_currency,
            quote_currency=base.quote_currency,
            digits=base.digits,
            point=base.point,
            contract_size=base.contract_size,
            volume_min=vmin,
            volume_max=max(vmin, vmax),
            volume_step=step,
            trade_allowed=base.trade_allowed,
            canonical=base.canonical,
            category=base.category,
            market_open=base.market_open,
        )
        self._specs[broker_name] = (info, multiplier, time.monotonic())
        return info

    # ── prices ───────────────────────────────────────────────────────────
    def get_quote(self, symbol: str) -> Quote:
        name = self.resolve(symbol)
        quote = self._quotes.get(name)
        if quote is not None and name in self._tick_subscribed:
            age = (self.now() - quote.time).total_seconds()
            if age < QUOTE_FRESH or not self._is_open(name):
                return quote
        try:
            reply = self._ws().request({"ticks": name, "subscribe": 1})
        except DerivApiError as exc:
            if (exc.subcode or exc.deriv_code) == "MarketIsClosed" and quote is not None:
                return quote
            raise _map_api_error(exc) from exc
        self._tick_subscribed.add(name)
        self._on_tick(reply)
        quote = self._quotes.get(name)
        if quote is None:
            raise InvalidBrokerResponseError(f"Deriv sent no price for {symbol}")
        return quote

    def _is_open(self, name: str) -> bool:
        item = self._active.get(name) or {}
        return bool(item.get("exchange_is_open"))

    def _price_in_account(self, info: SymbolInfo, broker_name: str) -> Decimal:
        """Value of ONE unit of the instrument in the account currency."""
        currency = self._account.currency if self._account else "USD"
        rate = conversion_rate(info.base_currency, currency, self._lookup)
        if rate is not None:
            return rate
        quote = self.get_quote(broker_name)  # non-currency instrument quoted in USD
        usd = conversion_rate(info.quote_currency, currency, self._lookup) or Decimal(1)
        return quote.mid * usd

    def _lookup(self, canonical: str) -> Quote | None:
        try:
            return self.get_quote(canonical)
        except BrokerError:
            return None

    def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        name = self.resolve(symbol)
        if timeframe.seconds not in GRANULARITIES:
            raise BrokerError(f"Deriv has no {timeframe} candles")
        now = self.now()
        candles: dict[datetime, Candle] = {}
        cursor = start
        chunk = timeframe.delta * 1000
        while cursor < end:
            stop = min(cursor + chunk, end)
            try:
                reply = self._ws().request(
                    {
                        "ticks_history": name,
                        "style": "candles",
                        "granularity": timeframe.seconds,
                        "start": int(cursor.timestamp()),
                        "end": int(stop.timestamp()),
                        "count": 1000,
                        "adjust_start_time": 0,
                    }
                )
            except DerivApiError as exc:
                raise BrokerError(f"Deriv candles unavailable: {exc}") from exc
            for row in reply.get("candles") or []:
                opened = _epoch(row.get("epoch"))
                values = [_dec(row.get(k)) for k in ("open", "high", "low", "close")]
                if opened is None or any(v is None for v in values):
                    continue
                if opened < start or opened >= end or opened + timeframe.delta > now:
                    continue  # outside the window, or still forming
                o, h, low, c = (v for v in values if v is not None)
                candles[opened] = Candle(opened, o, h, low, c)
            cursor = stop
        return [candles[t] for t in sorted(candles)]

    # ── positions & history ──────────────────────────────────────────────
    def _refresh_portfolio(self, *, force: bool = False) -> None:
        if not force and time.monotonic() - self._portfolio_at < PORTFOLIO_REFRESH:
            return
        reply = self._ws().request({"portfolio": 1, "contract_type": ["MULTUP", "MULTDOWN"]})
        contracts = (reply.get("portfolio") or {}).get("contracts") or []
        open_ids = {str(c["contract_id"]) for c in contracts if c.get("contract_id") is not None}
        for cid in list(self._contracts):
            if cid not in open_ids:
                self._contracts.pop(cid, None)  # closed; details come from history
        for cid in open_ids - set(self._contracts):
            self._fetch_contract(cid)
        self._portfolio_at = time.monotonic()

    def _fetch_contract(self, contract_id: str) -> dict[str, Any] | None:
        if contract_id in self._sold:
            return self._sold[contract_id]
        try:
            reply = self._ws().request(
                {"proposal_open_contract": 1, "contract_id": int(contract_id)}
            )
        except DerivApiError:
            return None
        self._on_contract(reply)
        poc = reply.get("proposal_open_contract")
        return poc if isinstance(poc, dict) else None

    def _compute_volume(
        self, info: SymbolInfo, stake: Decimal, multiplier: Decimal, entry: Decimal
    ) -> Decimal:
        """lots = notional ÷ (value of one lot in account currency) — the ONE formula
        used for fills, positions and history, so volumes always agree."""
        currency = self._account.currency if self._account else "USD"
        if info.base_currency == currency:
            rate = Decimal(1)
        elif info.quote_currency == currency:
            rate = entry
        else:
            rate = self._price_in_account(info, info.name)
        if rate <= 0:
            return Decimal(0)
        return (stake * multiplier / rate / info.contract_size).quantize(Decimal("0.0001"))

    def _units_of(self, contract_id: str, poc: dict[str, Any]) -> Decimal:
        if contract_id in self._units:
            return self._units[contract_id]
        stake = _dec(poc.get("buy_price")) or Decimal(0)
        multiplier = _dec(poc.get("multiplier")) or Decimal(0)
        entry = _dec(poc.get("entry_spot")) or _dec(poc.get("current_spot")) or Decimal(0)
        name = str(poc.get("underlying_symbol") or "")
        units = Decimal(0)
        if entry > 0 and name in self._active:
            units = self._compute_volume(
                self._base_info(self._active[name]), stake, multiplier, entry
            )
        self._units[contract_id] = units
        return units

    def _position(self, contract_id: str, poc: dict[str, Any]) -> Position:
        limits = poc.get("limit_order") or {}
        side = Side.BUY if poc.get("contract_type") == "MULTUP" else Side.SELL
        opened = _epoch(poc.get("date_start") or poc.get("purchase_time")) or self.now()
        entry = _dec(poc.get("entry_spot")) or _dec(poc.get("current_spot")) or Decimal(0)
        return Position(
            position_id=contract_id,
            symbol=str(poc.get("underlying_symbol") or ""),
            side=side,
            volume=self._units_of(contract_id, poc),
            open_price=entry,
            open_time=opened,
            stop_loss=_dec((limits.get("stop_loss") or {}).get("value")),
            take_profit=_dec((limits.get("take_profit") or {}).get("value")),
            unrealized_pnl=_dec(poc.get("profit")) or Decimal(0),
            client_order_id=self._client_by_contract.get(contract_id),
        )

    def get_positions(self) -> list[Position]:
        self._refresh_portfolio()
        return [self._position(cid, poc) for cid, poc in list(self._contracts.items())]

    def get_orders(self) -> list[Order]:
        return []  # Deriv multipliers have no resting (pending) orders

    def get_deals(self, start: datetime, end: datetime) -> list[Deal]:
        deals: list[Deal] = []
        offset = 0
        while True:
            try:
                reply = self._ws().request(
                    {
                        "profit_table": 1,
                        "description": 1,
                        "limit": 500,
                        "offset": offset,
                        "sort": "ASC",
                        "date_from": str(int(start.timestamp())),
                        "date_to": str(int(end.timestamp())),
                        "contract_type": ["MULTUP", "MULTDOWN"],
                    }
                )
            except DerivApiError as exc:
                raise BrokerError(f"Deriv history unavailable: {exc}") from exc
            rows = (reply.get("profit_table") or {}).get("transactions") or []
            for row in rows:
                deals.extend(self._deals_for(row))
            if len(rows) < 500:
                return deals
            offset += 500

    def _deals_for(self, row: dict[str, Any]) -> list[Deal]:
        cid = str(row.get("contract_id"))
        poc = self._fetch_contract(cid) or {}
        buy, sell = _dec(row.get("buy_price")), _dec(row.get("sell_price"))
        if buy is None or sell is None:
            return []
        side = (
            Side.BUY
            if (row.get("contract_type") or poc.get("contract_type")) == "MULTUP"
            else Side.SELL
        )
        units = self._units_of(cid, poc) if poc else Decimal(0)
        entry = _dec(poc.get("entry_spot")) or Decimal(0)
        exit_price = _dec(poc.get("exit_spot")) or _dec(poc.get("current_spot")) or entry
        opened = _epoch(row.get("purchase_time")) or self.now()
        closed = _epoch(row.get("sell_time")) or self.now()
        symbol = str(row.get("underlying_symbol") or poc.get("underlying_symbol") or "")
        client = self._client_by_contract.get(cid)
        return [
            Deal(
                deal_id=f"{cid}-in",
                order_id=str(row.get("transaction_id")),
                position_id=cid,
                symbol=symbol,
                side=side,
                entry=DealEntry.IN,
                volume=units,
                price=entry,
                time=opened,
                profit=Decimal(0),
                client_order_id=client,
            ),
            Deal(
                deal_id=f"{cid}-out",
                order_id=None,
                position_id=cid,
                symbol=symbol,
                side=side.opposite,
                entry=DealEntry.OUT,
                volume=units,
                price=exit_price,
                time=closed,
                profit=(sell - buy).quantize(CENT),  # Deriv prices already include commission
                reason=_exit_reason(poc, side, exit_price),
            ),
        ]

    def find_order_by_client_id(
        self, client_order_id: str, hint: OrderHint | None = None
    ) -> OrderResult | None:
        contract_id = self._contract_by_client.get(client_order_id)
        if contract_id is None and hint is not None and hint.submitted_at is not None:
            contract_id = self._match_contract(hint)
            if contract_id is not None:
                self._remember(client_order_id, contract_id)
        if contract_id is None:
            return None
        poc = self._contracts.get(contract_id) or self._fetch_contract(contract_id) or {}
        entry = _dec(poc.get("entry_spot"))
        return OrderResult(
            client_order_id=client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id=str((poc.get("transaction_ids") or {}).get("buy") or contract_id),
            broker_position_id=contract_id,
            filled_volume=self._units_of(contract_id, poc) if poc else Decimal(0),
            fill_price=entry,
            time=_epoch(poc.get("date_start")),
            broker_message="Matched to Deriv contract during reconciliation",
        )

    def _match_contract(self, hint: OrderHint) -> str | None:
        """Find an unclaimed contract that matches what we sent (no client id at Deriv)."""
        if hint.submitted_at is None:
            return None
        wanted_type = "MULTUP" if hint.side is Side.BUY else "MULTDOWN"
        try:
            symbol = self.resolve(hint.symbol)
        except BrokerError:
            symbol = hint.symbol
        lo, hi = hint.submitted_at - MATCH_BEFORE, hint.submitted_at + MATCH_AFTER
        self._refresh_portfolio(force=True)
        candidates: list[tuple[datetime, str]] = []
        for cid, poc in self._contracts.items():
            when = _epoch(poc.get("purchase_time") or poc.get("date_start"))
            if (
                cid not in self._client_by_contract
                and poc.get("underlying_symbol") == symbol
                and poc.get("contract_type") == wanted_type
                and when is not None
                and lo <= when <= hi
            ):
                candidates.append((when, cid))
        if not candidates:  # it may already have been closed (e.g. stopped out)
            with contextlib.suppress(BrokerError):
                for deal in self.get_deals(lo, hi + timedelta(days=1)):
                    if (
                        deal.entry is DealEntry.IN
                        and deal.symbol == symbol
                        and deal.side is hint.side
                        and lo <= deal.time <= hi
                        and deal.position_id
                        and deal.position_id not in self._client_by_contract
                    ):
                        candidates.append((deal.time, deal.position_id))
        return min(candidates)[1] if candidates else None

    def _remember(self, client_order_id: str, contract_id: str) -> None:
        self._contract_by_client[client_order_id] = contract_id
        self._client_by_contract[contract_id] = client_order_id

    # ── trading ──────────────────────────────────────────────────────────
    def _proposal(
        self,
        name: str,
        side: Side,
        stake: Decimal,
        multiplier: int,
        stop_amount: Decimal | None,
        take_amount: Decimal | None,
    ) -> dict[str, Any]:
        limit_order: dict[str, float] = {}
        if stop_amount is not None:
            limit_order["stop_loss"] = float(stop_amount)
        if take_amount is not None:
            limit_order["take_profit"] = float(take_amount)
        payload: dict[str, Any] = {
            "proposal": 1,
            "contract_type": "MULTUP" if side is Side.BUY else "MULTDOWN",
            "underlying_symbol": name,
            "amount": float(stake),
            "basis": "stake",
            "currency": self._account.currency if self._account else "USD",
            "multiplier": multiplier,
        }
        if limit_order:
            payload["limit_order"] = limit_order
        reply = self._ws().request(payload)
        proposal = reply.get("proposal")
        if not isinstance(proposal, dict) or not proposal.get("id"):
            raise InvalidBrokerResponseError("Deriv proposal response is malformed")
        return proposal

    @staticmethod
    def _amount(notional: Decimal, entry: Decimal, level: Decimal) -> Decimal:
        return (notional * abs(entry - level) / entry).quantize(CENT, ROUND_HALF_UP)

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.order_type is not OrderType.MARKET:
            raise OrderRejectedError(
                "Deriv does not offer pending (limit/stop) orders — use a market order.",
                broker_code="PendingOrdersUnsupported",
            )
        try:
            info = self.get_symbol(request.symbol)
            name = info.name
            multiplier = self._specs[name][1]
            quote = self.get_quote(name)
            rate = self._price_in_account(info, name)
        except BrokerConnectionError:
            raise
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        entry = quote.ask if request.side is Side.BUY else quote.bid
        stake = (request.volume * info.contract_size * rate / multiplier).quantize(CENT, ROUND_DOWN)
        if stake <= 0:
            raise OrderRejectedError("Volume is too small for a Deriv stake")
        notional = stake * multiplier
        stop_amount = (
            self._amount(notional, entry, request.stop_loss) if request.stop_loss else None
        )
        take_amount = (
            self._amount(notional, entry, request.take_profit) if request.take_profit else None
        )
        if stop_amount is not None and stop_amount > stake:
            max_move = (Decimal(100) / multiplier).quantize(Decimal("0.01"))
            raise OrderRejectedError(
                f"Stop loss is too far for Deriv ×{multiplier}: the most a stop can risk is the "
                f"stake ({stake} {self._account.currency if self._account else 'USD'}), "
                f"i.e. a {max_move}% price move.",
                broker_code="StopLossBeyondStake",
            )
        # 1. Price the contract. A refusal here means nothing was bought.
        try:
            proposal = self._proposal(
                name, request.side, stake, multiplier, stop_amount, take_amount
            )
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerTimeoutError as exc:
            raise BrokerConnectionError(f"Deriv did not price the order: {exc}") from exc
        ask = _dec(proposal.get("ask_price")) or stake
        sent_at = self.now()
        # 2. Buy. From here on a lost link means the outcome is UNKNOWN.
        try:
            reply = self._ws().request({"buy": proposal["id"], "price": float(ask)}, timeout=30)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerError as exc:
            raise OrderOutcomeUnknownError(
                f"Deriv buy not confirmed: {exc}", client_order_id=request.client_order_id
            ) from exc
        receipt = reply.get("buy") or {}
        if receipt.get("contract_id") is None:
            raise OrderOutcomeUnknownError(
                "Deriv buy receipt has no contract id", client_order_id=request.client_order_id
            )
        contract_id = str(receipt["contract_id"])
        self._remember(request.client_order_id, contract_id)
        poc = self._fetch_contract(contract_id) or {}
        fill = _dec(poc.get("entry_spot")) or _dec(proposal.get("spot")) or entry
        buy_price = _dec(receipt.get("buy_price")) or stake
        units = self._compute_volume(info, buy_price, Decimal(multiplier), fill)
        self._units[contract_id] = units
        return OrderResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id=str(receipt.get("transaction_id") or contract_id),
            broker_position_id=contract_id,
            filled_volume=units,
            fill_price=fill,
            time=_epoch(receipt.get("start_time") or receipt.get("purchase_time")) or sent_at,
            broker_message=f"Deriv ×{multiplier}, stake {buy_price}",
            raw={"stake": str(buy_price), "multiplier": str(multiplier)},
        )

    def close_position(
        self, position_id: str, client_order_id: str, volume: Decimal | None = None
    ) -> OrderResult:
        poc = self._contracts.get(position_id) or self._fetch_contract(position_id)
        if poc is None:
            raise OrderRejectedError(f"Deriv contract {position_id} not found")
        units = self._units_of(position_id, poc)
        if volume is not None and volume < units:
            raise OrderRejectedError("Deriv cannot partially close a multiplier contract")
        try:
            reply = self._ws().request({"sell": int(position_id), "price": 0}, timeout=30)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerError as exc:
            raise OrderOutcomeUnknownError(
                f"Deriv sell not confirmed: {exc}", client_order_id=client_order_id
            ) from exc
        receipt = reply.get("sell") or {}
        self._contracts.pop(position_id, None)
        self._sold.pop(position_id, None)  # refetch the final, sold state
        details = self._fetch_contract(position_id) or {}
        price = _dec(details.get("exit_spot")) or _dec(details.get("current_spot"))
        return OrderResult(
            client_order_id=client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id=str(receipt.get("transaction_id") or ""),
            broker_position_id=position_id,
            filled_volume=units,
            fill_price=price,
            time=self.now(),
            broker_message=f"Sold for {receipt.get('sold_for')}",
        )

    def modify_position(
        self, position_id: str, stop_loss: Decimal | None, take_profit: Decimal | None
    ) -> OrderResult:
        poc = self._contracts.get(position_id) or self._fetch_contract(position_id)
        if poc is None or poc.get("is_sold"):
            raise OrderRejectedError(f"Deriv contract {position_id} is not open")
        entry = _dec(poc.get("entry_spot"))
        stake = _dec(poc.get("buy_price"))
        multiplier = _dec(poc.get("multiplier"))
        if not entry or not stake or not multiplier:
            raise InvalidBrokerResponseError("Deriv contract details are incomplete")
        notional = stake * multiplier
        side = Side.BUY if poc.get("contract_type") == "MULTUP" else Side.SELL
        if stop_loss is not None and (entry - stop_loss) * side.sign <= 0:
            raise OrderRejectedError("Stop loss must be on the losing side of the entry price")
        stop_amount = self._amount(notional, entry, stop_loss) if stop_loss is not None else None
        if stop_amount is not None and stop_amount > stake:
            raise OrderRejectedError(
                f"Stop loss too far: Deriv limits the stop-loss amount to the stake ({stake})."
            )
        take_amount = (
            self._amount(notional, entry, take_profit) if take_profit is not None else None
        )
        try:
            self._ws().request(
                {
                    "contract_update": 1,
                    "contract_id": int(position_id),
                    "limit_order": {
                        "stop_loss": float(stop_amount) if stop_amount is not None else None,
                        "take_profit": float(take_amount) if take_amount is not None else None,
                    },
                }
            )
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        self._fetch_contract(position_id)
        return OrderResult(
            client_order_id=None,
            status=OrderStatus.FILLED,
            broker_position_id=position_id,
            time=self.now(),
        )

    def modify_order(self, order_id: str, changes: OrderModification) -> OrderResult:
        raise OrderRejectedError("Deriv has no pending orders to modify")

    def cancel_order(self, order_id: str) -> OrderResult:
        raise OrderRejectedError("Deriv has no pending orders to cancel")


def contract_size_of(name: str) -> Decimal:
    """MetaTrader-style contract size for a Deriv symbol."""
    if name.startswith("frx") and len(name) == 9:
        base = name[3:6]
        if base in ("XAU", "XPT", "XPD"):
            return Decimal(100)
        if base == "XAG":
            return Decimal(5000)
        return Decimal(100_000)
    return Decimal(1)


def _with_status(info: SymbolInfo, market_open: bool | None, trade_allowed: bool) -> SymbolInfo:
    from dataclasses import replace

    return replace(info, market_open=market_open, trade_allowed=trade_allowed)


def _exit_reason(poc: dict[str, Any], side: Side, exit_price: Decimal) -> str:
    limits = poc.get("limit_order") or {}
    stop = _dec((limits.get("stop_loss") or {}).get("value"))
    take = _dec((limits.get("take_profit") or {}).get("value"))
    stop_out = _dec((limits.get("stop_out") or {}).get("value"))
    if stop is not None and (stop - exit_price) * side.sign >= 0:
        return "SL"
    if take is not None and (exit_price - take) * side.sign >= 0:
        return "TP"
    if stop_out is not None and (stop_out - exit_price) * side.sign >= 0:
        return "SO"
    return "OTHER"
