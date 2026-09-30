"""Thin wrapper around the ``MetaTrader5`` module.

The ``MetaTrader5`` package is not thread-safe, so *every* call goes through one
single-thread executor. Callers submit whole synchronous units of work
(``fn(session) -> T``) which run atomically on that thread, with a timeout.
The module is injected so tests can pass a fake.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from . import errors

log = logging.getLogger("mt5_bridge.terminal")

T = TypeVar("T")

# MetaTrader5 last_error() codes
RES_S_OK = 1
RES_E_FAIL = -1
RES_E_INVALID_PARAMS = -2
RES_E_NOT_FOUND = -4
RES_E_AUTH_FAILED = -6
RES_E_AUTO_TRADING_DISABLED = -8
RES_E_INTERNAL_FAIL = -10000
RES_E_INTERNAL_FAIL_SEND = -10001
RES_E_INTERNAL_FAIL_RECEIVE = -10002
RES_E_INTERNAL_FAIL_INIT = -10003
RES_E_INTERNAL_FAIL_CONNECT = -10004
RES_E_INTERNAL_FAIL_TIMEOUT = -10005

IPC_ERRORS = frozenset(
    {
        RES_E_INTERNAL_FAIL,
        RES_E_INTERNAL_FAIL_SEND,
        RES_E_INTERNAL_FAIL_RECEIVE,
        RES_E_INTERNAL_FAIL_INIT,
        RES_E_INTERNAL_FAIL_CONNECT,
        RES_E_INTERNAL_FAIL_TIMEOUT,
    }
)


class TerminalTimeoutError(Exception):
    """The unit of work did not finish within its timeout."""


class Session:
    """State and helpers that live on the MT5 worker thread. Only touch from that thread."""

    def __init__(self, mt5: Any, terminal_path: str | None, connect_timeout_ms: int) -> None:
        self.mt5 = mt5
        self.terminal_path = terminal_path
        self.connect_timeout_ms = connect_timeout_ms
        self.initialized = False

    # -- errors ------------------------------------------------------------------
    def last_error(self) -> tuple[int, str]:
        try:
            err = self.mt5.last_error()
            return int(err[0]), str(err[1])
        except Exception:  # pragma: no cover - defensive
            return RES_E_FAIL, "unknown error"

    def error_from_last(self, what: str) -> errors.BridgeError:
        """Translate ``last_error()`` after a failed call into a protocol error."""
        code, msg = self.last_error()
        if code in IPC_ERRORS:
            self.initialized = False
            return errors.not_connected(f"{what}: terminal IPC failure ({msg})", str(code))
        if code == RES_E_AUTH_FAILED:
            return errors.broker_auth_failed(f"{what}: {msg}", str(code))
        return errors.internal(f"{what} failed: {msg} ({code})")

    # -- connection ----------------------------------------------------------------
    def ensure_initialized(self, path: str | None = None) -> None:
        mt5 = self.mt5
        if self.initialized and mt5.terminal_info() is not None:
            return
        kwargs: dict[str, Any] = {"timeout": self.connect_timeout_ms}
        p = path or self.terminal_path
        if p:
            kwargs["path"] = p
        if not mt5.initialize(**kwargs):
            code, msg = self.last_error()
            self.initialized = False
            raise errors.not_connected(f"Terminal initialisation failed: {msg}", str(code))
        self.initialized = True

    def ensure_connected(self) -> Any:
        """Ensure the terminal is initialised, connected and logged in. Returns account_info."""
        self.ensure_initialized()
        ti = self.mt5.terminal_info()
        if ti is None:
            self.initialized = False
            raise self._not_connected_from_last("Terminal not available")
        if not ti.connected:
            raise errors.not_connected("Terminal is not connected to the trade server")
        ai = self.mt5.account_info()
        if ai is None:
            raise self._not_connected_from_last("Terminal is not logged in")
        return ai

    def _not_connected_from_last(self, what: str) -> errors.BridgeError:
        code, msg = self.last_error()
        return errors.not_connected(f"{what} ({msg})", str(code))

    def ensure_symbol(self, symbol: str) -> Any:
        """Return symbol_info, selecting the symbol in Market Watch if needed."""
        mt5 = self.mt5
        info = mt5.symbol_info(symbol)
        if info is None:
            code, _ = self.last_error()
            if code in IPC_ERRORS:
                raise self.error_from_last("symbol_info")
            raise errors.symbol_unavailable(f"Symbol {symbol} does not exist")
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise errors.symbol_unavailable(f"Symbol {symbol} cannot be selected")
            info = mt5.symbol_info(symbol)
            if info is None:
                raise errors.symbol_unavailable(f"Symbol {symbol} cannot be selected")
        return info

    def list_or_raise(self, result: Any, what: str) -> list[Any]:
        """positions_get/orders_get/... return None on error, a tuple otherwise."""
        if result is None:
            code, _ = self.last_error()
            if code in (RES_S_OK, RES_E_NOT_FOUND, 0):
                return []
            raise self.error_from_last(what)
        return list(result)


class Terminal:
    """Serialises all MT5 calls on one worker thread with per-call timeouts."""

    def __init__(
        self,
        mt5: Any | None,
        terminal_path: str | None = None,
        connect_timeout_seconds: float = 90.0,
    ) -> None:
        self._mt5 = mt5
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5-worker")
        self.session: Session | None = (
            Session(mt5, terminal_path, int(connect_timeout_seconds * 1000))
            if mt5 is not None
            else None
        )
        self._closed = False

    @property
    def available(self) -> bool:
        return self.session is not None

    async def run(self, fn: Callable[[Session], T], timeout: float) -> T:
        """Run ``fn(session)`` on the worker thread. Raises :class:`TerminalTimeoutError`."""
        session = self.session
        if session is None:
            raise errors.not_connected("The MetaTrader5 package is not installed on this host")
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(self._executor, fn, session)
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as exc:
            log.warning("terminal call timed out", extra={"timeout_s": timeout})
            raise TerminalTimeoutError from exc

    def worker_thread_ids(self) -> set[int]:  # used by tests
        return {
            t.ident
            for t in threading.enumerate()
            if t.name.startswith("mt5-worker") and t.ident is not None
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        session = self.session

        def _shutdown(s: Session) -> None:
            if s.initialized:
                try:
                    s.mt5.shutdown()
                finally:
                    s.initialized = False

        if session is not None:
            try:
                self._executor.submit(_shutdown, session).result(timeout=5)
            except Exception:  # pragma: no cover - best effort
                log.warning("terminal shutdown failed", exc_info=True)
        self._executor.shutdown(wait=False, cancel_futures=True)
