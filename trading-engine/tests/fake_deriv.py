"""An in-memory imitation of the Deriv API (REST + trading WebSocket).

It implements the calls the adapter uses with the response shapes documented
at developers.deriv.com (2026 API): accounts/OTP over REST; balance, ticks,
ticks_history, active_symbols, contracts_for, proposal, buy, portfolio,
proposal_open_contract, contract_update, sell and profit_table over the
WebSocket. Multipliers follow multiplier arithmetic, so P/L, stop-loss levels
and balances behave like the real thing. Rise/Fall (CALL/PUT/CALLE/PUTE)
contracts are priced with a fixed payout and settled by `expire()`. Money
fields of proposal_open_contract are STRINGS, as in Deriv's schema.

Faults can be injected: market closed, buy timeouts, link drops after a buy.
"""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

ACCOUNT_ID = "DOT90004580"
TOKEN = "pat_test_token_123"
APP_ID = "app-test"

SYMBOLS = {
    "frxEURUSD": {
        "market": "forex",
        "submarket": "major_pairs",
        "name": "EUR/USD",
        "pip": "0.00001",
        "price": Decimal("1.10000"),
        "multipliers": [100, 200, 300, 500, 800],
    },
    "frxUSDJPY": {
        "market": "forex",
        "submarket": "major_pairs",
        "name": "USD/JPY",
        "pip": "0.001",
        "price": Decimal("150.000"),
        "multipliers": [100, 200, 300, 500, 800],
    },
    "R_100": {
        "market": "synthetic_index",
        "submarket": "random_index",
        "name": "Volatility 100 Index",
        "pip": "0.01",
        "price": Decimal("637.40"),
        "multipliers": [40, 100, 200, 300, 400],
    },
}


@dataclass
class Contract:
    contract_id: int
    symbol: str
    contract_type: str
    stake: Decimal
    multiplier: int
    entry: Decimal
    purchase_time: int
    stop_amount: Decimal | None
    take_amount: Decimal | None
    sold: bool = False
    sell_price: Decimal | None = None
    exit_spot: Decimal | None = None
    sell_time: int | None = None
    # Rise/Fall
    payout: Decimal | None = None
    duration: int | None = None
    duration_unit: str | None = None
    status: str = "open"
    valid_to_sell: bool = True

    @property
    def sign(self) -> int:
        return 1 if self.contract_type in ("MULTUP", "CALL", "CALLE") else -1

    @property
    def rise_fall(self) -> bool:
        return self.contract_type in ("CALL", "PUT", "CALLE", "PUTE")

    def level(self, amount: Decimal | None, losing: bool) -> str | None:
        if amount is None:
            return None
        move = amount / (self.stake * self.multiplier) * self.entry
        direction = -self.sign if losing else self.sign
        return str((self.entry + direction * move).quantize(Decimal("0.00001")))


@dataclass
class FakeDeriv:
    balance: Decimal = Decimal("10000")
    account_type: str = "demo"
    now: int = 1_791_154_000
    market_closed: set[str] = field(default_factory=set)
    timeout_next_buy: bool = False  # executes the buy but never replies
    drop_after_buy: bool = False  # executes the buy, then the link dies
    contracts: dict[int, Contract] = field(default_factory=dict)
    next_id: int = 11_542_203_500
    sockets: list[FakeSocket] = field(default_factory=list)
    otps_issued: int = 0
    requests: list[dict[str, Any]] = field(default_factory=list)
    prices: dict[str, Decimal] = field(
        default_factory=lambda: {k: Decimal(v["price"]) for k, v in SYMBOLS.items()}  # type: ignore[arg-type]
    )
    payout_ratio: Decimal = Decimal("0.95")  # Rise/Fall: profit per 1 of stake when won
    ask_markup: Decimal = Decimal(0)  # added to the ask price (to test "ask above stake")
    stake_limits: bool = True  # include validation_params.stake in proposals
    forget_proposals: int = 0  # the next N buys answer InvalidContractProposal
    drop_on_proposal: int = 0  # the next N proposals close the link without a reply
    suspended: set[str] = field(default_factory=set)
    history_from: int = 1_760_000_000  # oldest candle the server serves (history limit)

    # ── REST ─────────────────────────────────────────────────────────────
    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("Authorization")
            if auth != f"Bearer {TOKEN}":
                return httpx.Response(
                    401,
                    json={
                        "errors": [
                            {"status": 401, "code": "Unauthorized", "message": "Invalid token"}
                        ]
                    },
                )
            if request.headers.get("Deriv-App-ID") != APP_ID:
                return httpx.Response(
                    401,
                    json={
                        "errors": [
                            {
                                "status": 401,
                                "code": "Unauthorized",
                                "message": "Deriv-App-ID header is required for PAT tokens",
                            }
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/trading/v1/options/accounts":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "account_id": ACCOUNT_ID,
                                "balance": float(self.balance),
                                "currency": "USD",
                                "group": "row",
                                "status": "active",
                                "account_type": self.account_type,
                            }
                        ],
                        "meta": {},
                    },
                )
            if request.method == "POST" and request.url.path.endswith("/otp"):
                self.otps_issued += 1
                kind = "demo" if self.account_type == "demo" else "real"
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "url": f"wss://api.derivws.com/trading/v1/options/ws/{kind}?otp=otp{self.otps_issued}"
                        }
                    },
                )
            return httpx.Response(
                404, json={"errors": [{"code": "NotFound", "message": "no route"}]}
            )

        return httpx.MockTransport(handler)

    def connector(self, url: str) -> FakeSocket:
        assert "otp=" in url, "trading WebSocket must use an OTP URL"
        socket = FakeSocket(self)
        self.sockets.append(socket)
        return socket

    # ── market helpers ───────────────────────────────────────────────────
    def set_price(self, symbol: str, price: str) -> None:
        self.prices[symbol] = Decimal(price)

    def price(self, symbol: str) -> Decimal:
        return self.prices[symbol]

    def _profit(self, c: Contract) -> Decimal:
        if c.rise_fall:
            if c.sold:
                return ((c.sell_price or Decimal(0)) - c.stake).quantize(Decimal("0.01"))
            return Decimal(0)
        price = c.exit_spot if c.sold and c.exit_spot is not None else self.price(c.symbol)
        return (c.stake * c.multiplier * (price - c.entry) / c.entry * c.sign).quantize(
            Decimal("0.01")
        )

    def _poc(self, c: Contract) -> dict[str, Any]:
        if c.rise_fall:
            return self._poc_rise_fall(c)
        profit = self._profit(c)
        limit: dict[str, Any] = {}
        if c.stop_amount is not None:
            limit["stop_loss"] = {
                "order_amount": float(-c.stop_amount),
                "value": c.level(c.stop_amount, True),
            }
        if c.take_amount is not None:
            limit["take_profit"] = {
                "order_amount": float(c.take_amount),
                "value": c.level(c.take_amount, False),
            }
        limit["stop_out"] = {"order_amount": float(-c.stake), "value": c.level(c.stake, True)}
        return {
            "contract_id": c.contract_id,
            "contract_type": c.contract_type,
            "currency": "USD",
            "underlying_symbol": c.symbol,
            "buy_price": str(c.stake),
            "bid_price": str(c.stake + profit) if not c.sold else str(c.sell_price),
            "profit": str(profit),
            "multiplier": c.multiplier,
            "entry_spot": str(c.entry),
            "current_spot": str(self.price(c.symbol)),
            "exit_spot": str(c.exit_spot) if c.exit_spot is not None else None,
            "date_start": c.purchase_time,
            "purchase_time": c.purchase_time,
            "is_sold": 1 if c.sold else 0,
            "status": "sold" if c.sold else "open",
            "limit_order": limit,
            "transaction_ids": {"buy": c.contract_id * 2},
            "sell_price": str(c.sell_price) if c.sell_price is not None else None,
            "sell_time": c.sell_time,
        }

    def _poc_rise_fall(self, c: Contract) -> dict[str, Any]:
        secs = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(c.duration_unit or "", 0)
        poc: dict[str, Any] = {
            "contract_id": c.contract_id,
            "contract_type": c.contract_type,
            "currency": "USD",
            "underlying_symbol": c.symbol,
            "buy_price": f"{c.stake:.2f}",
            "payout": f"{c.payout:.2f}",
            "bid_price": f"{(c.sell_price if c.sold else c.stake) or 0:.2f}",
            "profit": f"{self._profit(c):.2f}",
            "entry_spot": str(c.entry),
            "current_spot": str(self.price(c.symbol)),
            "exit_spot": str(c.exit_spot) if c.exit_spot is not None else None,
            "date_start": c.purchase_time,
            "purchase_time": c.purchase_time,
            "is_sold": 1 if c.sold else 0,
            "is_expired": 1 if c.sold else 0,
            "is_valid_to_sell": 1 if (c.valid_to_sell and not c.sold) else 0,
            "status": c.status,
            "longcode": f"Win payout if {c.symbol} is strictly higher than entry spot.",
            "transaction_ids": {"buy": c.contract_id * 2},
            "sell_price": f"{c.sell_price:.2f}" if c.sell_price is not None else None,
            "sell_time": c.sell_time,
        }
        if secs:  # tick contracts have no date_expiry
            poc["date_expiry"] = c.purchase_time + (c.duration or 0) * secs
        return poc

    def expire(self, contract_id: int, exit_price: str) -> None:
        """Settle a Rise/Fall at expiry (as Deriv does, without any request from us)."""
        c = self.contracts[contract_id]
        exit_ = Decimal(exit_price)
        won = {
            "CALL": exit_ > c.entry,
            "CALLE": exit_ >= c.entry,
            "PUT": exit_ < c.entry,
            "PUTE": exit_ <= c.entry,
        }[c.contract_type]
        c.exit_spot, c.sold, c.sell_time = exit_, True, self.now
        c.status = "won" if won else "lost"
        c.sell_price = c.payout if won else Decimal("0.00")
        self.balance += c.sell_price or Decimal(0)

    def close_externally(self, contract_id: int) -> None:
        """Simulate the broker closing a contract (stop loss hit)."""
        c = self.contracts[contract_id]
        c.exit_spot = Decimal(c.level(c.stop_amount or c.stake, True) or c.entry)
        c.sold = True
        c.sell_price = (c.stake - (c.stop_amount or c.stake)).quantize(Decimal("0.01"))
        c.sell_time = self.now
        self.balance += c.sell_price

    # ── WebSocket protocol ───────────────────────────────────────────────
    def handle(self, socket: FakeSocket, msg: dict[str, Any]) -> list[dict[str, Any]] | None:
        self.requests.append(msg)
        req_id = msg.get("req_id")

        def reply(msg_type: str, body: Any, **extra: Any) -> list[dict[str, Any]]:
            return [
                {"msg_type": msg_type, msg_type: body, "req_id": req_id, "echo_req": msg, **extra}
            ]

        def error(
            msg_type: str, code: str, message: str, subcode: str | None = None
        ) -> list[dict[str, Any]]:
            err: dict[str, Any] = {"code": code, "message": message}
            if subcode:
                err["subcode"] = subcode
            return [{"msg_type": msg_type, "error": err, "req_id": req_id, "echo_req": msg}]

        if "ping" in msg:
            return reply("ping", "pong")
        if "balance" in msg:
            return reply(
                "balance",
                {"balance": float(self.balance), "currency": "USD", "loginid": ACCOUNT_ID},
            )
        if "active_symbols" in msg:
            return reply(
                "active_symbols",
                [
                    {
                        "underlying_symbol": name,
                        "underlying_symbol_name": spec["name"],
                        "underlying_symbol_type": spec["market"],
                        "market": spec["market"],
                        "submarket": spec["submarket"],
                        "pip_size": float(Decimal(spec["pip"])),  # type: ignore[arg-type]
                        "exchange_is_open": 0 if name in self.market_closed else 1,
                        "is_trading_suspended": 1 if name in self.suspended else 0,
                    }
                    for name, spec in SYMBOLS.items()
                ],
            )
        if "contracts_for" in msg:
            spec = SYMBOLS[msg["contracts_for"]]
            available: list[dict[str, Any]] = [
                {
                    "contract_category": "multiplier",
                    "contract_type": t,
                    "multiplier_range": spec["multipliers"],
                }
                for t in ("MULTUP", "MULTDOWN")
            ]
            if msg["contracts_for"] == "R_100":  # Rise/Fall offered on the synthetic index
                for t in ("CALL", "PUT", "CALLE", "PUTE"):
                    available.append(
                        {
                            "contract_category": "callput",
                            "contract_type": t,
                            "expiry_type": "tick",
                            "barriers": 0,
                            "min_contract_duration": "1t",
                            "max_contract_duration": "10t",
                        }
                    )
                    available.append(
                        {
                            "contract_category": "callput",
                            "contract_type": t,
                            "expiry_type": "intraday",
                            "barriers": 0,
                            "min_contract_duration": "15s",
                            "max_contract_duration": "1d",
                        }
                    )
                # Higher/Lower: same types WITH a barrier — not Rise/Fall.
                available.append(
                    {
                        "contract_category": "callput",
                        "contract_type": "CALL",
                        "expiry_type": "daily",
                        "barriers": 1,
                        "min_contract_duration": "1d",
                        "max_contract_duration": "365d",
                    }
                )
            return reply("contracts_for", {"available": available})
        if "ticks" in msg:
            symbol = msg["ticks"]
            if symbol in self.market_closed:
                return error("tick", "MarketIsClosed", "This market is presently closed.")
            if msg.get("subscribe"):
                socket.ticks.add(symbol)
            price = self.price(symbol)
            return reply(
                "tick",
                {
                    "symbol": symbol,
                    "quote": float(price),
                    "ask": float(price),
                    "bid": float(price),
                    "epoch": self.now,
                },
            )
        if "ticks_history" in msg:
            # As Deriv's servers behave (checked 2026-10): `end` must be a string,
            # adjust_start_time only accepts 1, `start` does not select a window
            # (the latest bars come back), and an `end` before the history limit
            # also returns the latest bars.
            if not isinstance(msg.get("end"), str) or msg.get("adjust_start_time", 1) != 1:
                return error(
                    "ticks_history", "InputValidationFailed", "Input validation failed: end"
                )
            gran = int(msg.get("granularity", 60))
            count = int(msg.get("count", 1000))
            end = self.now if msg["end"] == "latest" else min(int(msg["end"]), self.now)
            if "start" in msg or end < self.history_from:
                end = self.now
            last = end - end % gran
            price = self.price(msg["ticks_history"])
            candles = [
                {
                    "epoch": t,
                    "open": float(price),
                    "high": float(price) * 1.001,
                    "low": float(price) * 0.999,
                    "close": float(price),
                }
                for t in range(max(last - (count - 1) * gran, self.history_from), last + 1, gran)
                if t >= self.history_from
            ]
            return reply("candles", candles)
        if "proposal" in msg and "proposal_open_contract" not in msg:
            if self.drop_on_proposal > 0:
                self.drop_on_proposal -= 1
                socket.drop()  # the link dies before Deriv answers
                return None
            symbol = msg["underlying_symbol"]
            spec = SYMBOLS[symbol]
            if symbol in self.market_closed:
                return error(
                    "proposal",
                    "ContractBuyValidationError",
                    "This market is presently closed.",
                    "MarketIsClosed",
                )
            if msg["contract_type"] in ("CALL", "PUT", "CALLE", "PUTE"):
                return self._rise_fall_proposal(socket, msg, reply)
            if msg["multiplier"] not in spec["multipliers"]:  # type: ignore[operator]
                return error(
                    "proposal",
                    "ContractBuyValidationError",
                    "Multiplier is not in acceptable range.",
                    "MultiplierOutOfRange",
                )
            stake = Decimal(str(msg["amount"]))
            stop = (msg.get("limit_order") or {}).get("stop_loss")
            if stop is not None and Decimal(str(stop)) > stake:
                return error(
                    "proposal",
                    "ContractBuyValidationError",
                    "Stop loss cannot be more than stake.",
                    "StopLossValidation",
                )
            proposal_id = f"prop-{len(self.requests)}"
            socket.proposals[proposal_id] = msg
            return reply(
                "proposal",
                {
                    "id": proposal_id,
                    "ask_price": float(stake),
                    "spot": float(self.price(symbol)),
                    "multiplier": msg["multiplier"],
                    "validation_params": {
                        # The shape Deriv's public servers returned for R_10 (2026-10).
                        "stake": {"min": "1.00", "max": "2000.00"},
                        "stop_loss": {"min": "0.10", "max": str(stake)},
                        "take_profit": {"min": "0.10", "max": "50.00"},
                    },
                },
            )
        if "buy" in msg:
            if str(msg["buy"]) == "1":  # bought by parameters (no proposal id)
                proposal = dict(msg.get("parameters") or {})
                missing = {"contract_type", "currency", "underlying_symbol"} - set(proposal)
                if missing:
                    return error("buy", "InputValidationFailed", f"Missing {sorted(missing)}")
            else:
                proposal = socket.proposals.pop(str(msg["buy"]), None)
            if proposal is not None and self.forget_proposals > 0:
                self.forget_proposals -= 1
                proposal = None
            if proposal is None:
                return error("buy", "InvalidContractProposal", "Proposal expired or already used.")
            stake = Decimal(str(proposal["amount"]))
            if stake > self.balance:
                return error("buy", "InsufficientBalance", "Your account balance is insufficient.")
            if Decimal(str(msg.get("price", 0))) < stake + self.ask_markup:
                return error("buy", "PriceMoved", "The price has changed.")
            if proposal["contract_type"] in ("CALL", "PUT", "CALLE", "PUTE"):
                return self._rise_fall_buy(socket, proposal, reply)
            limits = proposal.get("limit_order") or {}
            self.next_id += 1
            contract = Contract(
                contract_id=self.next_id,
                symbol=proposal["underlying_symbol"],
                contract_type=proposal["contract_type"],
                stake=stake,
                multiplier=int(proposal["multiplier"]),
                entry=self.price(proposal["underlying_symbol"]),
                purchase_time=self.now,
                stop_amount=Decimal(str(limits["stop_loss"])) if "stop_loss" in limits else None,
                take_amount=Decimal(str(limits["take_profit"]))
                if "take_profit" in limits
                else None,
            )
            self.contracts[contract.contract_id] = contract
            self.balance -= stake
            if self.timeout_next_buy:
                self.timeout_next_buy = False
                return None  # executed, but no reply ever arrives
            if self.drop_after_buy:
                self.drop_after_buy = False
                socket.drop()
                return None
            return reply(
                "buy",
                {
                    "contract_id": contract.contract_id,
                    "transaction_id": contract.contract_id * 2,
                    "buy_price": float(stake),
                    "balance_after": float(self.balance),
                    "start_time": self.now,
                    "purchase_time": self.now,
                    "longcode": "multiplier",
                    "shortcode": "MULT",
                    "payout": 0,
                },
            )
        if "portfolio" in msg:
            return reply(
                "portfolio",
                {
                    "contracts": [
                        {
                            "contract_id": c.contract_id,
                            "contract_type": c.contract_type,
                            "underlying_symbol": c.symbol,
                            "buy_price": float(c.stake),
                            "purchase_time": c.purchase_time,
                        }
                        for c in self.contracts.values()
                        if not c.sold
                    ]
                },
            )
        if "proposal_open_contract" in msg:
            cid = msg.get("contract_id")
            if cid is None:  # stream of all open contracts
                return reply("proposal_open_contract", {})
            contract = self.contracts.get(int(cid))
            if contract is None:
                return error("proposal_open_contract", "ContractNotFound", "Contract not found.")
            return reply("proposal_open_contract", self._poc(contract))
        if "contract_update" in msg:
            contract = self.contracts.get(int(msg["contract_id"]))
            if contract is None or contract.sold:
                return error("contract_update", "ContractNotFound", "Contract not found.")
            limits = msg.get("limit_order") or {}
            contract.stop_amount = (
                Decimal(str(limits["stop_loss"])) if limits.get("stop_loss") is not None else None
            )
            contract.take_amount = (
                Decimal(str(limits["take_profit"]))
                if limits.get("take_profit") is not None
                else None
            )
            return reply("contract_update", {})
        if "sell" in msg:
            contract = self.contracts.get(int(msg["sell"]))
            if contract is None or contract.sold:
                return error("sell", "InvalidSellContractProposal", "Contract already sold.")
            if contract.rise_fall:
                if not contract.valid_to_sell:
                    return error("sell", "InvalidSellContractProposal", "Resale not offered.")
                contract.sold, contract.status = True, "sold"
                contract.exit_spot = self.price(contract.symbol)
                contract.sell_price = (contract.stake * Decimal("0.5")).quantize(Decimal("0.01"))
                contract.sell_time = self.now
                self.balance += contract.sell_price
                return reply(
                    "sell",
                    {
                        "contract_id": contract.contract_id,
                        "sold_for": f"{contract.sell_price:.2f}",
                        "transaction_id": contract.contract_id * 3,
                        "balance_after": float(self.balance),
                    },
                )
            profit = self._profit(contract)
            contract.sold = True
            contract.exit_spot = self.price(contract.symbol)
            contract.sell_price = contract.stake + profit
            contract.sell_time = self.now
            self.balance += contract.sell_price
            return reply(
                "sell",
                {
                    "contract_id": contract.contract_id,
                    "sold_for": float(contract.sell_price),
                    "transaction_id": contract.contract_id * 3,
                    "reference_id": contract.contract_id * 2,
                    "balance_after": float(self.balance),
                },
            )
        if "profit_table" in msg:
            rows = [
                {
                    "contract_id": c.contract_id,
                    "transaction_id": c.contract_id * 3,
                    "buy_price": float(c.stake),
                    "sell_price": float(c.sell_price or 0),
                    "purchase_time": c.purchase_time,
                    "sell_time": c.sell_time,
                    "contract_type": c.contract_type,
                    "underlying_symbol": c.symbol,
                    "payout": float(c.payout or 0),
                }
                for c in self.contracts.values()
                if c.sold
            ]
            return reply("profit_table", {"count": len(rows), "transactions": rows})
        return error(str(next(iter(msg))), "UnrecognisedRequest", "Unrecognised request.")

    def _rise_fall_proposal(self, socket: FakeSocket, msg: dict[str, Any], reply: Any) -> Any:
        symbol = msg["underlying_symbol"]
        stake = Decimal(str(msg["amount"]))
        proposal_id = f"prop-{len(self.requests)}"
        socket.proposals[proposal_id] = msg
        body: dict[str, Any] = {
            "id": proposal_id,
            "ask_price": float(stake + self.ask_markup),
            "payout": float((stake * (1 + self.payout_ratio)).quantize(Decimal("0.01"))),
            "spot": float(self.price(symbol)),
            "longcode": f"Win payout if {symbol} is strictly higher than entry spot.",
            "commission": "0",
        }
        if self.stake_limits:
            body["validation_params"] = {"stake": {"min": "0.35", "max": "50000.00"}}
        return reply("proposal", body)

    def _rise_fall_buy(self, socket: FakeSocket, proposal: dict[str, Any], reply: Any) -> Any:
        stake = Decimal(str(proposal["amount"]))
        self.next_id += 1
        contract = Contract(
            contract_id=self.next_id,
            symbol=proposal["underlying_symbol"],
            contract_type=proposal["contract_type"],
            stake=stake,
            multiplier=0,
            entry=self.price(proposal["underlying_symbol"]),
            purchase_time=self.now,
            stop_amount=None,
            take_amount=None,
            payout=(stake * (1 + self.payout_ratio)).quantize(Decimal("0.01")),
            duration=int(proposal["duration"]),
            duration_unit=str(proposal["duration_unit"]),
        )
        self.contracts[contract.contract_id] = contract
        self.balance -= stake
        if self.timeout_next_buy:
            self.timeout_next_buy = False
            return None
        return reply(
            "buy",
            {
                "contract_id": contract.contract_id,
                "transaction_id": contract.contract_id * 2,
                "buy_price": float(stake),
                "payout": float(contract.payout or 0),
                "balance_after": float(self.balance),
                "start_time": self.now,
                "purchase_time": self.now,
                "longcode": f"Win payout if {contract.symbol} is strictly higher than entry spot.",
                "shortcode": f"{contract.contract_type}_{contract.symbol}",
            },
        )


class FakeSocket:
    """Looks like a `websockets` sync connection to DerivSocket."""

    def __init__(self, server: FakeDeriv) -> None:
        self.server = server
        self.inbox: queue.Queue[str | None] = queue.Queue()
        self.ticks: set[str] = set()
        self.proposals: dict[str, dict[str, Any]] = {}
        self.closed = False
        self._lock = threading.Lock()

    def send(self, message: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        with self._lock:
            replies = self.server.handle(self, json.loads(message))
        for item in replies or []:
            self.inbox.put(json.dumps(item))

    def recv(self, timeout: float | None = None) -> str:
        try:
            item = self.inbox.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError from exc
        if item is None:
            raise ConnectionError("closed")
        return item

    def push_tick(self, symbol: str) -> None:
        price = self.server.price(symbol)
        self.inbox.put(
            json.dumps(
                {
                    "msg_type": "tick",
                    "tick": {"symbol": symbol, "quote": float(price), "epoch": self.server.now},
                }
            )
        )

    def drop(self) -> None:
        self.closed = True
        self.inbox.put(None)

    def close(self) -> None:
        self.drop()
