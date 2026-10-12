"""Deriv adapter — Options API (developers.deriv.com, 2026 API).

How Deriv maps onto the 2kPilot broker contract
--------------------------------------------------
Deriv Options are CONTRACTS bought for a stake, not lots. Strategies still say
BUY or SELL; the contract spec of the assignment decides what is bought:

* Rise/Fall   BUY → CALL (CALLE when "allow equals"), SELL → PUT (PUTE).
  Bought with `proposal` {underlying_symbol, contract_type, basis: "stake",
  amount, currency, duration, duration_unit} → `buy` {buy: <proposal id>,
  price: <ask_price>}. It settles at expiry: won → payout − stake, lost →
  −stake (CALL/PUT lose when the exit spot equals the entry spot).
* Multipliers BUY → MULTUP, SELL → MULTDOWN, with `multiplier` and optional
  `limit_order` {take_profit, stop_loss} MONEY amounts. Profit ≈ stake ×
  multiplier × price change ÷ entry − commission; Deriv stops the contract out
  before the loss exceeds the stake.

Sizing is the stake (the risk profile's `stake_amount` or the assignment's
own stake); `volume` is one contract. A strategy's stop/target PRICES are
converted to money amounts for Multipliers when no amounts are configured.

Safety
* Prices are checked before buying: the buy is refused when Deriv's ask price
  is above the stake (plus a cent of rounding) — we never pay more than asked.
* Money fields of `proposal_open_contract` arrive as STRINGS and are parsed as
  Decimal (never float); spots are `entry_spot` / `exit_spot`.
* idempotency — Deriv does not store a client order id. Every intent is
  remembered, and after a timeout/restart reconciliation matches contracts by
  symbol, contract type, stake and purchase time (`OrderHint`), including
  contracts that already settled (`profit_table`), skipping contracts the
  database already ties to another order. An uncertain order is never re-sent,
  and "no such contract" is only answered after BOTH `portfolio` and
  `profit_table` were read; a failed read raises, so the order stays UNKNOWN.
* Once Deriv acknowledged a buy/sell (the receipt has a contract id), later
  failures (fetching the contract details) never turn it into "not executed":
  the fill is built from the receipt and the details are synced later.
* Early close is only attempted when Deriv says `is_valid_to_sell`; a Rise/Fall
  that cannot be sold settles at expiry.
* `contracts_for` (durations, multipliers) and `active_symbols`
  (`exchange_is_open`, `is_trading_suspended`) are cached per symbol and drive
  what can be traded. Stake limits are read from each proposal's
  `validation_params.stake` — never hard-coded.

Not verified against live servers (see docs/BROKERS.md): the exact
`contracts_for` grouping of Rise/Fall vs Higher/Lower (we keep CALL/PUT entries
without a barrier), `profit_table` money field types (parsed defensively), and
the `status` values of multipliers closed by take profit / stop loss.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fxrobot.broker_engine.adapters.deriv_client import (
    Connector,
    DerivAccount,
    DerivApiError,
    DerivRest,
    DerivSocket,
    RateLimiter,
    default_connector,
)
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerRateLimitError,
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
from fxrobot.domain.contracts import (
    ContractCapabilities,
    ContractFamily,
    ContractFill,
    ContractOrder,
    ContractType,
    DurationRange,
    StakeQuote,
    multiplier_limit_amounts,
)
from fxrobot.domain.modes import AccountEnvironment

CENT = Decimal("0.01")
ASK_TOLERANCE = Decimal("0.01")  # rounding allowance between stake and ask price
SYMBOLS_TTL = 600.0  # seconds
# A market listed as closed is asked about again sooner, so trading resumes within
# a minute of the open (forex: Monday 00:00 UTC) instead of up to SYMBOLS_TTL later.
CLOSED_RECHECK = 60.0
CONTRACTS_TTL = 600.0
QUOTE_FRESH = 10.0
PORTFOLIO_REFRESH = 30.0
MATCH_BEFORE = timedelta(seconds=10)  # clock skew allowance when matching contracts
MATCH_AFTER = timedelta(minutes=3)
# One portfolio + profit_table read serves every uncertain order reconciled
# within this many seconds (Deriv allows ~30 of those calls a minute).
MATCH_REUSE = 10.0
MATCH_HISTORY_SPAN = timedelta(hours=1)  # history read further back, so orders share it

CONTRACT_TYPES = [t.value for t in ContractType]
RISE_FALL_TYPES = ("CALL", "PUT", "CALLE", "PUTE")
STATUS_OUTCOME = {"won": "WON", "lost": "LOST", "sold": "SOLD", "cancelled": "CANCELLED"}

CATEGORIES = {
    "forex": "forex",
    "synthetic_index": "synthetic",
    "indices": "indices",
    "commodities": "commodities",
    "cryptocurrency": "crypto",
    "stocks": "stocks",
}
GRANULARITIES = {60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400}
HISTORY_MAX_PAGES = 400  # × 1000 candles per ticks_history request


def _dec(value: Any) -> Decimal | None:
    """Deriv money fields are strings (sometimes numbers): always Decimal, never float."""
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


def _flag(value: Any) -> bool:
    return value in (1, True, "1")


def _rise_fall_rows(offered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `contracts_for` rows that are Rise/Fall (CALL/PUT without a barrier).

    Older replies list Rise/Fall (`barriers: 0`, "euro_atm") apart from
    Higher/Lower (`barriers: 1`, "euro_non_atm"). Deriv's current Options API
    (checked 2026-10 on Volatility indices) lists one CALL/PUT row per expiry
    with `barriers: 1` and no `barrier_category`: the barrier is optional and a
    proposal without one is Rise/Fall. Each trade is still priced by a
    proposal first, so Deriv confirms the contract before anything is bought.
    """
    call_put = [c for c in offered if str(c.get("contract_type")) in RISE_FALL_TYPES]
    atm = [
        c
        for c in call_put
        if c.get("barrier_category") == "euro_atm"
        or str(c.get("barriers") if c.get("barriers") is not None else 0) in ("0", "")
    ]
    if atm:
        return atm
    return [c for c in call_put if not c.get("barrier_category")]


def _contract_type(value: Any) -> ContractType | None:
    try:
        return ContractType(str(value))
    except ValueError:
        return None


def _map_api_error(exc: DerivApiError) -> OrderRejectedError:
    code = exc.subcode or exc.deriv_code
    if code == "MarketIsClosed" or exc.deriv_code == "MarketIsClosed":
        return MarketClosedError(str(exc), broker_code=code)
    if code in ("InsufficientBalance", "InsufficientFunds"):
        return InsufficientMarginError(str(exc), broker_code=code)
    return OrderRejectedError(str(exc), broker_code=code)


logger = logging.getLogger(__name__)


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
        volume_unit="stake",
        contract_families=("RISE_FALL", "MULTIPLIER"),
        notes=(
            "Trades are Deriv Options contracts bought for a stake: Rise/Fall "
            "(CALL/PUT) or Multipliers (MULTUP/MULTDOWN).",
            "A contract can lose at most its stake. Rise/Fall settles at expiry; "
            "payouts vary with every price quote.",
            "No pending orders and no partial closes.",
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
        limiter: RateLimiter | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("A Deriv account id is required")
        self.account_id = account_id
        self._rest = rest or DerivRest(token=token, app_id=app_id, token_kind=token_kind)
        self._connector = connector
        self._clock = clock
        # Connection setting kept for older configurations: the multiplier a manual
        # Multiplier ticket uses when it does not choose one.
        self.default_multiplier = multiplier
        self._limiter = limiter or RateLimiter()  # one budget per connection, across reconnects
        self._socket: DerivSocket | None = None
        self._account: DerivAccount | None = None
        self._lock = threading.RLock()
        # caches (filled from responses and streams)
        self._active: dict[str, dict[str, Any]] = {}
        self._active_at = 0.0
        self._offered: dict[str, tuple[list[dict[str, Any]], float]] = {}  # contracts_for
        self._quotes: dict[str, Quote] = {}
        self._tick_subscribed: set[str] = set()
        self._contracts: dict[str, dict[str, Any]] = {}  # contract_id -> latest POC
        self._sold: dict[str, dict[str, Any]] = {}  # immutable details of closed contracts
        self._balance: Decimal | None = None
        self._portfolio_at = 0.0
        # idempotency bookkeeping
        self._client_by_contract: dict[str, str] = {}
        self._contract_by_client: dict[str, str] = {}
        # (history start, read at [monotonic], deals): shared by reconciliation matches
        self._history: tuple[datetime, float, list[Deal]] | None = None

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
            socket = DerivSocket(url, connector=self._connector, limiter=self._limiter)
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
        if _flag(poc.get("is_sold")) or str(poc.get("status") or "") in STATUS_OUTCOME:
            self._contracts.pop(cid, None)
            self._sold[cid] = poc  # settled (expired, sold, stopped out): history from here
        else:
            self._contracts[cid] = poc

    # ── account ──────────────────────────────────────────────────────────
    def get_account(self) -> AccountInfo:
        if self._account is None:
            raise BrokerConnectionError("Not connected to Deriv")
        account = self._account
        if self.is_connected:  # cheap (100/min budget); the stream also keeps it fresh
            with contextlib.suppress(BrokerTimeoutError, BrokerRateLimitError):
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
            # The stake of an open contract is already debited; its current
            # value (bid price) is part of equity.
            equity=balance + open_value,
            trade_allowed=account.status == "active",
        )

    @property
    def currency(self) -> str:
        return self._account.currency if self._account else "USD"

    # ── symbols ──────────────────────────────────────────────────────────
    def _active_symbols(self, max_age: float = SYMBOLS_TTL) -> dict[str, dict[str, Any]]:
        if self._active and time.monotonic() - self._active_at < max_age:
            return self._active
        reply = self._ws().request({"active_symbols": "brief"})
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
    def _currencies(name: str) -> tuple[str, str, str]:
        """(canonical, base, quote) for a Deriv symbol."""
        if name.startswith("frx") and len(name) == 9:
            pair = name[3:]
            return pair, pair[:3], pair[3:]
        if name.startswith("cry") and name.endswith("USD"):
            return name[3:], name[3:-3], "USD"
        return name, name, "USD"  # indices & synthetics are quoted in USD

    def _base_info(self, item: dict[str, Any]) -> SymbolInfo:
        name = str(item["underlying_symbol"])
        canonical, base, quote = self._currencies(name)
        pip = _dec(item.get("pip_size")) or Decimal("0.01")
        digits = max(0, -pip.normalize().as_tuple().exponent)  # type: ignore[operator]
        suspended = _flag(item.get("is_trading_suspended"))
        return SymbolInfo(
            name=name,
            description=str(item.get("underlying_symbol_name") or name),
            base_currency=base,
            quote_currency=quote,
            digits=digits,
            point=pip,
            contract_size=Decimal(1),
            # One contract per order; lots do not apply to Options.
            volume_min=Decimal(1),
            volume_max=Decimal(1),
            volume_step=Decimal(1),
            trade_allowed=not suspended,
            canonical=canonical,
            category=CATEGORIES.get(str(item.get("market")), "other"),
            market_open=_flag(item.get("exchange_is_open")) and not suspended,
        )

    def get_symbols(self) -> list[SymbolInfo]:
        return [self._base_info(i) for i in self._active_symbols().values()]

    def get_symbol(self, name: str) -> SymbolInfo:
        broker_name = self.resolve(name)
        if not _flag(self._active[broker_name].get("exchange_is_open")):
            self._active_symbols(max_age=CLOSED_RECHECK)
        return self._base_info(self._active[broker_name])

    # ── contracts offered (contracts_for) ────────────────────────────────
    def _contracts_for(self, broker_name: str) -> list[dict[str, Any]]:
        cached = self._offered.get(broker_name)
        if cached and time.monotonic() - cached[1] < CONTRACTS_TTL:
            return cached[0]
        reply = self._ws().request({"contracts_for": broker_name})
        offered = (reply.get("contracts_for") or {}).get("available") or []
        items = [c for c in offered if isinstance(c, dict)]
        self._offered[broker_name] = (items, time.monotonic())
        return items

    def contract_capabilities(self, symbol: str) -> ContractCapabilities:
        name = self.resolve(symbol)
        item = self._active[name]
        offered = self._contracts_for(name)
        rise_fall = _rise_fall_rows(offered)
        durations: list[DurationRange] = []
        for c in rise_fall:
            lo, hi = c.get("min_contract_duration"), c.get("max_contract_duration")
            if lo and hi:
                rng = DurationRange(
                    str(c.get("expiry_type")) if c.get("expiry_type") else None, str(lo), str(hi)
                )
                if rng not in durations:
                    durations.append(rng)
        multipliers = sorted(
            {
                int(m)
                for c in offered
                if str(c.get("contract_type")) in ("MULTUP", "MULTDOWN")
                for m in (c.get("multiplier_range") or [])
                if str(m).isdigit()
            }
        )
        offered_types = {str(c.get("contract_type")) for c in rise_fall}
        types = tuple(t for t in RISE_FALL_TYPES if t in offered_types)
        return ContractCapabilities(
            symbol=name,
            rise_fall=bool(durations) and {"CALL", "PUT"} <= set(types),
            rise_fall_types=types,
            durations=tuple(durations),
            multipliers=tuple(multipliers),
            spot=False,
            market_open=_flag(item.get("exchange_is_open")),
            trading_suspended=_flag(item.get("is_trading_suspended")),
            notes=(
                "From Deriv contracts_for (cached 10 minutes).",
                "Payouts and stake limits come from each live price quote (proposal).",
            ),
        )

    def quote_contract(self, symbol: str, contract: ContractOrder) -> StakeQuote:
        """Ask Deriv to price the contract (nothing is bought): stake limits and payout."""
        name = self.resolve(symbol)
        try:
            proposal = self._proposal_reconnecting(name, contract, None)
        except (DerivApiError, BrokerRateLimitError, InvalidBrokerResponseError) as exc:
            return StakeQuote(None, None, detail=f"Deriv did not price it: {exc}")
        params = proposal.get("validation_params") or {}
        stake = params.get("stake") or {}
        stop = params.get("stop_loss") or {}  # Multipliers only
        take = params.get("take_profit") or {}
        return StakeQuote(
            stake_min=_dec(stake.get("min")),
            stake_max=_dec(stake.get("max")),
            ask_price=_dec(proposal.get("ask_price")),
            payout=_dec(proposal.get("payout")),
            detail=(
                ""
                if stake.get("min") and stake.get("max")
                else f"Deriv's proposal validation_params.stake: {stake or 'none'}"
            ),
            stop_loss_min=_dec(stop.get("min")),
            stop_loss_max=_dec(stop.get("max")),
            take_profit_min=_dec(take.get("min")),
            take_profit_max=_dec(take.get("max")),
        )

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
        return _flag(item.get("exchange_is_open"))

    def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Closed candles from `ticks_history` (style "candles") — public market data.

        Checked against Deriv's public servers (2026-10): `end` is a STRING
        ("latest" or epoch digits), `adjust_start_time` only accepts 1, and a
        request with `start` returns the LATEST candles whatever the window. So we
        page BACKWARDS with `end` + `count` only. Beyond Deriv's history limit the
        server answers with the latest candles instead — that ends the paging.
        """
        name = self.resolve(symbol)
        if timeframe.seconds not in GRANULARITIES:
            raise BrokerError(f"Deriv has no {timeframe} candles")
        now = self.now()
        candles: dict[datetime, Candle] = {}
        cursor = min(end, now)
        for _ in range(HISTORY_MAX_PAGES):
            if cursor <= start:
                break
            try:
                reply = self._ws().request(
                    {
                        "ticks_history": name,
                        "style": "candles",
                        "granularity": timeframe.seconds,
                        "end": str(int(cursor.timestamp())),
                        "count": 1000,
                    }
                )
            except DerivApiError as exc:
                raise BrokerError(f"Deriv candles unavailable: {exc}") from exc
            rows = [r for r in reply.get("candles") or [] if _epoch(r.get("epoch")) is not None]
            if not rows:
                break
            first = min(e for r in rows if (e := _epoch(r.get("epoch"))) is not None)
            last = max(e for r in rows if (e := _epoch(r.get("epoch"))) is not None)
            if last > cursor + timeframe.delta:
                break  # beyond the history limit: Deriv answered with the latest bars
            for row in rows:
                opened = _epoch(row.get("epoch"))
                values = [_dec(row.get(k)) for k in ("open", "high", "low", "close")]
                if opened is None or any(v is None for v in values):
                    continue
                if opened < start or opened >= end or opened + timeframe.delta > now:
                    continue  # outside the window, or still forming
                o, h, low, c = (v for v in values if v is not None)
                candles[opened] = Candle(opened, o, h, low, c)
            if first >= cursor:
                break  # no progress
            cursor = first
        return [candles[t] for t in sorted(candles)]

    # ── positions & history ──────────────────────────────────────────────
    def _refresh_portfolio(self, *, force: bool = False) -> None:
        if not force and time.monotonic() - self._portfolio_at < PORTFOLIO_REFRESH:
            return
        reply = self._ws().request({"portfolio": 1, "contract_type": CONTRACT_TYPES})
        contracts = (reply.get("portfolio") or {}).get("contracts") or []
        open_ids = {str(c["contract_id"]) for c in contracts if c.get("contract_id") is not None}
        for cid in list(self._contracts):
            if cid not in open_ids:
                self._contracts.pop(cid, None)  # settled; details come from history
        for cid in open_ids - set(self._contracts):
            self._fetch_contract(cid)
        self._portfolio_at = time.monotonic()

    def _fetch_contract(
        self, contract_id: str, *, refresh: bool = False, strict: bool = False
    ) -> dict[str, Any] | None:
        """Latest details of one contract; None when Deriv refuses (or, unless
        `strict`, when our request budget is used up — strict callers retry later)."""
        if contract_id in self._sold and not refresh:
            return self._sold[contract_id]
        try:
            reply = self._ws().request(
                {"proposal_open_contract": 1, "contract_id": int(contract_id)}
            )
        except DerivApiError:
            return None
        except BrokerRateLimitError:
            if strict:
                raise
            return None
        self._on_contract(reply)
        poc = reply.get("proposal_open_contract")
        return poc if isinstance(poc, dict) else None

    def _position(self, contract_id: str, poc: dict[str, Any]) -> Position:
        limits = poc.get("limit_order") or {}
        ctype = _contract_type(poc.get("contract_type"))
        side = ctype.side if ctype is not None else Side.BUY
        opened = _epoch(poc.get("date_start") or poc.get("purchase_time")) or self.now()
        entry = _dec(poc.get("entry_spot")) or _dec(poc.get("current_spot")) or Decimal(0)
        multiplier = _dec(poc.get("multiplier"))
        is_rise_fall = ctype is not None and ctype.family is ContractFamily.RISE_FALL
        return Position(
            position_id=contract_id,
            symbol=str(poc.get("underlying_symbol") or ""),
            side=side,
            volume=Decimal(1),
            open_price=entry,
            open_time=opened,
            stop_loss=_dec((limits.get("stop_loss") or {}).get("value")),
            take_profit=_dec((limits.get("take_profit") or {}).get("value")),
            unrealized_pnl=_dec(poc.get("profit")) or Decimal(0),
            client_order_id=self._client_by_contract.get(contract_id),
            contract_type=ctype,
            stake=_dec(poc.get("buy_price")),
            payout=_dec(poc.get("payout")) if is_rise_fall else None,
            multiplier=int(multiplier) if multiplier else None,
            expires_at=_epoch(poc.get("date_expiry")) if poc.get("date_expiry") else None,
            is_valid_to_sell=_flag(poc.get("is_valid_to_sell"))
            if poc.get("is_valid_to_sell") is not None
            else None,
        )

    def get_positions(self) -> list[Position]:
        self._refresh_portfolio()
        return [self._position(cid, poc) for cid, poc in list(self._contracts.items())]

    def get_orders(self) -> list[Order]:
        return []  # Deriv contracts have no resting (pending) orders

    def get_deals(self, start: datetime, end: datetime) -> list[Deal]:
        """Settled contracts from `profit_table` (also those settled while we were offline).

        A contract we saw settle (its sold `proposal_open_contract`, with
        `sell_price`) but that `profit_table` does not list yet is reported from
        those cached details, so its P/L is never lost to history lag.
        """
        deals: list[Deal] = []
        listed: set[str] = set()
        offset = 0
        try:
            while True:
                reply = self._ws().request(
                    {
                        "profit_table": 1,
                        "description": 1,
                        "limit": 500,
                        "offset": offset,
                        "sort": "ASC",
                        "date_from": str(int(start.timestamp())),
                        "date_to": str(int(end.timestamp())),
                        "contract_type": CONTRACT_TYPES,
                    }
                )
                rows = (reply.get("profit_table") or {}).get("transactions") or []
                for row in rows:
                    listed.add(str(row.get("contract_id")))
                    deals.extend(self._deals_for(row))
                if len(rows) < 500:
                    break
                offset += 500
            for cid, poc in list(self._sold.items()):
                row = _sold_row(poc)
                opened, closed = _epoch(row["purchase_time"]), _epoch(row["sell_time"])
                if (
                    cid not in listed
                    and row["sell_price"] is not None
                    and opened is not None
                    and closed is not None
                    and opened <= end
                    and closed >= start
                ):
                    deals.extend(self._deals_for(row))
        except (DerivApiError, BrokerRateLimitError) as exc:
            raise BrokerError(f"Deriv history unavailable: {exc}") from exc
        return deals

    def _deals_for(self, row: dict[str, Any]) -> list[Deal]:
        cid = str(row.get("contract_id"))
        # strict: a rate-limited lookup must not record entry/exit 0 or guess the
        # exit reason — the whole read fails and is retried on a later tick.
        poc = self._fetch_contract(cid, strict=True) or {}
        buy, sell = _dec(row.get("buy_price")), _dec(row.get("sell_price"))
        if buy is None or sell is None:
            return []
        ctype = _contract_type(row.get("contract_type") or poc.get("contract_type"))
        side = ctype.side if ctype is not None else Side.BUY
        entry = _dec(poc.get("entry_spot")) or Decimal(0)
        exit_price = _dec(poc.get("exit_spot")) or _dec(poc.get("current_spot")) or entry
        opened = _epoch(row.get("purchase_time")) or self.now()
        closed = _epoch(row.get("sell_time")) or self.now()
        symbol = str(row.get("underlying_symbol") or poc.get("underlying_symbol") or "")
        client = self._client_by_contract.get(cid)
        profit = (sell - buy).quantize(CENT)  # Deriv prices already include commission
        status = str(poc.get("status") or "").lower()
        outcome = STATUS_OUTCOME.get(status) or ("WON" if profit > 0 else "LOST")
        is_rise_fall = ctype is not None and ctype.family is ContractFamily.RISE_FALL
        if is_rise_fall:
            reason = "CLIENT" if status == "sold" else "EXPIRY"
        else:
            reason = _exit_reason(poc, side, exit_price)
            # A Multiplier closed by its take profit / stop loss / stop out won or lost;
            # one closed any other way (e.g. sold by us) is SOLD.
            outcome = ("WON" if profit > 0 else "LOST") if reason in ("SL", "TP", "SO") else "SOLD"
        payout = _dec(row.get("payout")) or _dec(poc.get("payout"))
        type_name = ctype.value if ctype is not None else None
        return [
            Deal(
                deal_id=f"{cid}-in",
                order_id=str(row.get("transaction_id")),
                position_id=cid,
                symbol=symbol,
                side=side,
                entry=DealEntry.IN,
                volume=Decimal(1),
                price=entry,
                time=opened,
                profit=Decimal(0),
                client_order_id=client,
                contract_type=type_name,
            ),
            Deal(
                deal_id=f"{cid}-out",
                order_id=None,
                position_id=cid,
                symbol=symbol,
                side=side.opposite,
                entry=DealEntry.OUT,
                volume=Decimal(1),
                price=exit_price,
                time=closed,
                profit=profit,
                reason=reason,
                outcome=outcome,
                payout=payout if is_rise_fall else None,
                contract_type=type_name,
            ),
        ]

    def _fill_from(self, contract_id: str, poc: dict[str, Any]) -> ContractFill | None:
        ctype = _contract_type(poc.get("contract_type"))
        buy_price = _dec(poc.get("buy_price"))
        if ctype is None or buy_price is None:
            return None
        multiplier = _dec(poc.get("multiplier"))
        return ContractFill(
            contract_id=contract_id,
            contract_type=ctype,
            buy_price=buy_price,
            payout=_dec(poc.get("payout")) if ctype.family is ContractFamily.RISE_FALL else None,
            transaction_id=str((poc.get("transaction_ids") or {}).get("buy") or "") or None,
            start_time=_epoch(poc.get("date_start") or poc.get("purchase_time")),
            expires_at=_epoch(poc.get("date_expiry")) if poc.get("date_expiry") else None,
            longcode=str(poc.get("longcode")) if poc.get("longcode") else None,
            multiplier=int(multiplier) if multiplier else None,
            entry_spot=_dec(poc.get("entry_spot")),
            commission=_dec(poc.get("commission")),
        )

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
            filled_volume=Decimal(1),
            fill_price=entry,
            time=_epoch(poc.get("date_start")),
            broker_message="Matched to Deriv contract during reconciliation",
            contract=self._fill_from(contract_id, poc),
        )

    def _match_contract(self, hint: OrderHint) -> str | None:
        """Find an unclaimed contract that matches what we sent (no client id at Deriv).

        Looks at open contracts first (and contracts we saw settle), then at
        settled ones (`profit_table`): a Rise/Fall may already have expired by
        the time we reconcile. Contracts claimed by another order — in memory or
        in the database (`hint.claimed_ids`) — are never matched. Among several
        candidates the one whose stake and purchase time best fit the order wins.

        Raises BrokerError when `portfolio` or `profit_table` cannot be read:
        "no match" is only answered when both were read for the window.
        """
        if hint.submitted_at is None:
            return None
        if hint.contract_type is not None:
            wanted = {hint.contract_type.value}
        else:
            wanted = {"MULTUP" if hint.side is Side.BUY else "MULTDOWN"}
        try:
            symbol = self.resolve(hint.symbol)
        except SymbolUnavailableError:
            symbol = hint.symbol
        lo, hi = hint.submitted_at - MATCH_BEFORE, hint.submitted_at + MATCH_AFTER
        claimed = set(self._client_by_contract) | set(hint.claimed_ids)
        if time.monotonic() - self._portfolio_at > MATCH_REUSE:
            self._refresh_portfolio(force=True)
        candidates: list[tuple[str, datetime, Decimal | None]] = []
        for cid, poc in [*self._contracts.items(), *self._sold.items()]:
            when = _epoch(poc.get("purchase_time") or poc.get("date_start"))
            if (
                cid not in claimed
                and poc.get("underlying_symbol") == symbol
                and poc.get("contract_type") in wanted
                and when is not None
                and lo <= when <= hi
            ):
                candidates.append((cid, when, _dec(poc.get("buy_price"))))
        if not candidates:  # it may already have settled (expired, stopped out)
            for deal in self._history_since(lo):
                if (
                    deal.entry is DealEntry.IN
                    and deal.symbol == symbol
                    and deal.contract_type in wanted
                    and lo <= deal.time <= hi
                    and deal.position_id
                    and deal.position_id not in claimed
                ):
                    stake = _dec((self._sold.get(deal.position_id) or {}).get("buy_price"))
                    candidates.append((deal.position_id, deal.time, stake))
        if not candidates:
            return None
        sent = hint.submitted_at

        def fit(item: tuple[str, datetime, Decimal | None]) -> tuple[int, float, str]:
            cid, when, stake = item
            stake_off = int(
                hint.stake is not None and (stake is None or abs(stake - hint.stake) > CENT)
            )
            return stake_off, abs((when - sent).total_seconds()), cid

        return min(candidates, key=fit)[0]

    def _history_since(self, start: datetime) -> list[Deal]:
        """Settled contracts since `start`, read once for all orders reconciled
        together. Only reused when read AFTER the portfolio we just checked, so
        a contract that settled in between is never missed."""
        cached = self._history
        if cached is not None and cached[0] <= start and cached[1] >= self._portfolio_at:
            return cached[2]
        begin = start - MATCH_HISTORY_SPAN
        deals = self.get_deals(begin, self.now() + timedelta(days=1))
        self._history = (begin, time.monotonic(), deals)
        return deals

    def _remember(self, client_order_id: str, contract_id: str) -> None:
        self._contract_by_client[client_order_id] = contract_id
        self._client_by_contract[contract_id] = client_order_id

    # ── trading ──────────────────────────────────────────────────────────
    def _reopen(self) -> None:
        """Replace a dropped Deriv link (a fresh one-time password, a new socket)."""
        self.disconnect()
        self.connect()

    def _proposal_reconnecting(
        self, name: str, contract: ContractOrder, limit_order: dict[str, float] | None
    ) -> dict[str, Any]:
        """Price the contract; if the link dropped, reconnect once and price again.
        Pricing buys nothing, so repeating it is always safe."""
        try:
            return self._proposal(name, contract, limit_order)
        except BrokerConnectionError:
            logger.info("Deriv link dropped while pricing %s; reconnecting", name)
            self._reopen()
            return self._proposal(name, contract, limit_order)

    def _proposal(
        self, name: str, contract: ContractOrder, limit_order: dict[str, float] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "proposal": 1,
            "contract_type": contract.contract_type.value,
            "underlying_symbol": name,
            "basis": "stake",
            "amount": float(contract.stake),
            "currency": self.currency,
        }
        if contract.family is ContractFamily.RISE_FALL:
            payload["duration"] = contract.duration
            payload["duration_unit"] = contract.duration_unit
        else:
            payload["multiplier"] = contract.multiplier
            if limit_order:
                payload["limit_order"] = limit_order
        reply = self._ws().request(payload)
        proposal = reply.get("proposal")
        if not isinstance(proposal, dict) or not proposal.get("id"):
            raise InvalidBrokerResponseError("Deriv proposal response is malformed")
        return proposal

    def place_order(self, request: OrderRequest) -> OrderResult:
        if request.order_type is not OrderType.MARKET:
            raise OrderRejectedError(
                "Deriv does not offer pending (limit/stop) orders — use a market order.",
                broker_code="PendingOrdersUnsupported",
            )
        contract = request.contract
        if contract is None:
            raise OrderRejectedError(
                "Deriv trades Options contracts: choose Rise/Fall or Multiplier "
                "(lot-based SPOT trading is Paper only).",
                broker_code="ContractRequired",
            )
        if contract.contract_type.side is not request.side:
            raise OrderRejectedError("Contract type does not match the order direction")
        try:
            name = self.resolve(request.symbol)
            problem = self.contract_capabilities(name).check(contract.as_spec())
            limit_order: dict[str, float] = {}
            if contract.family is ContractFamily.MULTIPLIER:
                stop, take = contract.stop_loss_amount, contract.take_profit_amount
                if stop is None and take is None and contract.multiplier:
                    quote = self.get_quote(name)
                    entry = quote.ask if request.side is Side.BUY else quote.bid
                    stop, take = multiplier_limit_amounts(
                        request.side,
                        contract.stake,
                        contract.multiplier,
                        entry,
                        request.stop_loss,
                        request.take_profit,
                    )
                if stop is not None:
                    limit_order["stop_loss"] = float(stop)
                if take is not None:
                    limit_order["take_profit"] = float(take)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerRateLimitError as exc:
            raise OrderRejectedError(str(exc), broker_code="RateLimited") from exc
        except (SymbolUnavailableError, InvalidBrokerResponseError) as exc:
            raise OrderRejectedError(str(exc)) from exc  # nothing was sent
        except BrokerTimeoutError as exc:
            raise BrokerConnectionError(f"Deriv did not answer before the order: {exc}") from exc
        if problem:
            raise OrderRejectedError(problem, broker_code="ContractNotOffered")
        # Deriv answers InvalidContractProposal when the quote it priced is no longer
        # valid (seen live 2026-10-12 on frxUSDJPY): nothing was bought, so price
        # once more and buy that.
        for attempt in (1, 2):
            try:
                return self._price_and_buy(request, name, contract, limit_order)
            except OrderRejectedError as exc:
                if attempt == 2 or exc.broker_code != "InvalidContractProposal":
                    raise
                logger.info("Deriv no longer knew the proposal for %s; pricing again", name)
        raise AssertionError("unreachable")

    def _price_and_buy(
        self,
        request: OrderRequest,
        name: str,
        contract: ContractOrder,
        limit_order: dict[str, float],
    ) -> OrderResult:
        # 1. Price the contract. A refusal here means nothing was bought.
        try:
            proposal = self._proposal_reconnecting(name, contract, limit_order)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerRateLimitError as exc:
            raise OrderRejectedError(str(exc), broker_code="RateLimited") from exc
        except (BrokerTimeoutError, InvalidBrokerResponseError) as exc:
            raise BrokerConnectionError(f"Deriv did not price the order: {exc}") from exc
        ask = _dec(proposal.get("ask_price"))
        if ask is None:
            raise OrderRejectedError("Deriv's price quote had no ask price — nothing was bought")
        if ask > contract.stake + ASK_TOLERANCE:
            raise OrderRejectedError(
                f"Deriv asks {ask} for a {contract.stake} {self.currency} stake — refused, "
                "2kPilot never pays more than the stake.",
                broker_code="AskAboveStake",
            )
        sent_at = self.now()
        # 2. Buy at no more than the quoted ask. From here on a lost link = UNKNOWN.
        try:
            reply = self._ws().request({"buy": proposal["id"], "price": float(ask)}, timeout=30)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerRateLimitError as exc:  # refused before sending
            raise OrderRejectedError(str(exc), broker_code="RateLimited") from exc
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
        # Deriv acknowledged the buy: from here nothing may report "not bought".
        # Details are a nicety — without them the receipt is the fill.
        try:
            poc = self._fetch_contract(contract_id) or {}
        except BrokerError:
            poc = {}
        start = _epoch(receipt.get("start_time") or receipt.get("purchase_time")) or sent_at
        buy_price = _dec(receipt.get("buy_price")) or ask
        entry_spot = _dec(poc.get("entry_spot")) or _dec(proposal.get("spot"))
        expires = _epoch(poc.get("date_expiry")) if poc.get("date_expiry") else None
        is_rise_fall = contract.family is ContractFamily.RISE_FALL
        fill = ContractFill(
            contract_id=contract_id,
            contract_type=contract.contract_type,
            buy_price=buy_price,
            payout=(_dec(receipt.get("payout")) or _dec(proposal.get("payout")))
            if is_rise_fall
            else None,
            transaction_id=str(receipt.get("transaction_id") or "") or None,
            start_time=start,
            expires_at=expires or (contract.expires_at(start) if is_rise_fall else None),
            longcode=str(receipt.get("longcode") or proposal.get("longcode") or "") or None,
            multiplier=contract.multiplier,
            duration=contract.duration,
            duration_unit=contract.duration_unit,
            entry_spot=entry_spot,
            commission=_dec(poc.get("commission")),
        )
        return OrderResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id=fill.transaction_id or contract_id,
            broker_position_id=contract_id,
            filled_volume=Decimal(1),
            fill_price=entry_spot,
            time=start,
            broker_message=(fill.longcode or f"Deriv {contract.contract_type.value}")[:500],
            raw={"stake": str(buy_price), "contract_type": contract.contract_type.value},
            contract=fill,
        )

    def close_position(
        self, position_id: str, client_order_id: str, volume: Decimal | None = None
    ) -> OrderResult:
        poc = self._fetch_contract(position_id, refresh=True) or self._contracts.get(position_id)
        if poc is None:
            raise OrderRejectedError(f"Deriv contract {position_id} not found")
        if volume is not None and volume < 1:
            raise OrderRejectedError("Deriv cannot partially close a contract")
        if _flag(poc.get("is_sold")):
            raise OrderRejectedError("This contract has already settled")
        if poc.get("is_valid_to_sell") is not None and not _flag(poc.get("is_valid_to_sell")):
            ctype = _contract_type(poc.get("contract_type"))
            if ctype is not None and ctype.family is ContractFamily.RISE_FALL:
                raise OrderRejectedError(
                    "This contract settles at expiry: Deriv does not allow selling it now.",
                    broker_code="NotValidToSell",
                )
            raise OrderRejectedError(
                "Deriv does not allow selling this contract right now.",
                broker_code="NotValidToSell",
            )
        try:
            reply = self._ws().request({"sell": int(position_id), "price": 0}, timeout=30)
        except DerivApiError as exc:
            raise _map_api_error(exc) from exc
        except BrokerRateLimitError as exc:
            raise OrderRejectedError(str(exc), broker_code="RateLimited") from exc
        except BrokerError as exc:
            raise OrderOutcomeUnknownError(
                f"Deriv sell not confirmed: {exc}", client_order_id=client_order_id
            ) from exc
        receipt = reply.get("sell") or {}
        self._contracts.pop(position_id, None)
        self._sold.pop(position_id, None)  # refetch the final, sold state
        try:  # the sale is acknowledged: a failed detail fetch must not undo it
            details = self._fetch_contract(position_id) or {}
        except BrokerError:
            details = {}
        price = _dec(details.get("exit_spot")) or _dec(details.get("current_spot"))
        return OrderResult(
            client_order_id=client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id=str(receipt.get("transaction_id") or ""),
            broker_position_id=position_id,
            filled_volume=Decimal(1),
            fill_price=price,
            time=self.now(),
            broker_message=f"Sold for {_dec(receipt.get('sold_for'))}",
        )

    def modify_position(
        self, position_id: str, stop_loss: Decimal | None, take_profit: Decimal | None
    ) -> OrderResult:
        poc = self._contracts.get(position_id) or self._fetch_contract(position_id)
        if poc is None or _flag(poc.get("is_sold")):
            raise OrderRejectedError(f"Deriv contract {position_id} is not open")
        ctype = _contract_type(poc.get("contract_type"))
        if ctype is None or ctype.family is not ContractFamily.MULTIPLIER:
            raise OrderRejectedError("Only Multiplier contracts have a stop loss / take profit")
        entry = _dec(poc.get("entry_spot"))
        stake = _dec(poc.get("buy_price"))
        multiplier = _dec(poc.get("multiplier"))
        if not entry or not stake or not multiplier:
            raise InvalidBrokerResponseError("Deriv contract details are incomplete")
        notional = stake * multiplier
        side = ctype.side
        if stop_loss is not None and (entry - stop_loss) * side.sign <= 0:
            raise OrderRejectedError("Stop loss must be on the losing side of the entry price")
        stop_amount = _amount(notional, entry, stop_loss) if stop_loss is not None else None
        if stop_amount is not None and stop_amount > stake:
            raise OrderRejectedError(
                f"Stop loss too far: Deriv limits the stop-loss amount to the stake ({stake})."
            )
        take_amount = _amount(notional, entry, take_profit) if take_profit is not None else None
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


def _amount(notional: Decimal, entry: Decimal, level: Decimal) -> Decimal:
    return (notional * abs(entry - level) / entry).quantize(CENT, ROUND_HALF_UP)


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


def _sold_row(poc: dict[str, Any]) -> dict[str, Any]:
    """A `profit_table`-shaped row from a settled contract's own details."""
    return {
        "contract_id": poc.get("contract_id"),
        "transaction_id": (poc.get("transaction_ids") or {}).get("sell")
        or (poc.get("transaction_ids") or {}).get("buy"),
        "buy_price": poc.get("buy_price"),
        "sell_price": poc.get("sell_price"),
        "purchase_time": poc.get("purchase_time") or poc.get("date_start"),
        "sell_time": poc.get("sell_time") or poc.get("exit_tick_time") or poc.get("date_expiry"),
        "contract_type": poc.get("contract_type"),
        "underlying_symbol": poc.get("underlying_symbol"),
        "payout": poc.get("payout"),
    }
