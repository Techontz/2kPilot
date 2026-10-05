"""Engine supervisor: leadership lease, heartbeat, per-account worker threads."""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.db.types import utcnow
from fxrobot.models import BrokerConnection, SystemState, TradingAccount
from fxrobot.notifications.service import notify
from fxrobot.trading_engine.runner import AccountRunner, TickResult

logger = logging.getLogger(__name__)

LEASE = timedelta(seconds=30)
ACCOUNT_TICK_TIMEOUT = 45.0


class TradingEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        manager: BrokerManager,
        *,
        live_locked: bool,
        tick_seconds: float = 2.0,
    ) -> None:
        self._sf = session_factory
        self.manager = manager
        self.runner = AccountRunner(manager, live_locked=live_locked)
        self.tick_seconds = tick_seconds
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fx-account")
        self.is_leader = False
        self._db_down_notified = False

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fx-engine", daemon=True)
        self._thread.start()
        logger.info("trading engine started (%s)", self.owner)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.manager.flush_all()
        self._release_lease()
        logger.info("trading engine stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
                self._db_down_notified = False
            except SQLAlchemyError:
                # Database unavailable: do nothing (no DB = no safe decisions), retry.
                if not self._db_down_notified:
                    logger.exception("database unavailable — engine paused until it returns")
                    self._db_down_notified = True
            except Exception:
                logger.exception("engine cycle failed")
                self._notify_error("Trading engine cycle failed; see server logs.")
            self._stop.wait(self.tick_seconds)

    # ── leadership ───────────────────────────────────────────────────────
    def _acquire_lease(self, db: Session) -> bool:
        now = utcnow()
        result = db.execute(
            update(SystemState)
            .where(SystemState.id == 1)
            .where(
                or_(
                    SystemState.engine_owner.is_(None),
                    SystemState.engine_owner == self.owner,
                    SystemState.engine_lease_until < now,
                )
            )
            .values(engine_owner=self.owner, engine_lease_until=now + LEASE)
        )
        db.commit()
        leader = bool(result.rowcount)  # type: ignore[attr-defined]
        if leader and not self.is_leader:
            logger.info("engine leadership acquired")
        self.is_leader = leader
        return leader

    def _release_lease(self) -> None:
        try:
            with self._sf() as db:
                db.execute(
                    update(SystemState)
                    .where(SystemState.engine_owner == self.owner)
                    .values(engine_owner=None, engine_lease_until=None)
                )
                db.commit()
        except SQLAlchemyError:
            pass

    # ── cycle ────────────────────────────────────────────────────────────
    def run_cycle(self) -> list[TickResult]:
        with self._sf() as db:
            if not self._acquire_lease(db):
                return []
            account_ids = list(
                db.scalars(
                    select(TradingAccount.id)
                    .join(BrokerConnection)
                    .where(BrokerConnection.is_enabled.is_(True))
                )
            )
        futures = {self._pool.submit(self._tick_account, aid): aid for aid in account_ids}
        results: list[TickResult] = []
        done, pending = wait(futures, timeout=ACCOUNT_TICK_TIMEOUT)
        for future in done:
            try:
                results.append(future.result())
            except Exception as exc:
                logger.exception("account tick crashed")
                results.append(TickResult(futures[future], False, f"internal error: {exc}"))
        for future in pending:
            results.append(TickResult(futures[future], False, "tick timed out"))
        self._heartbeat(results)
        return results

    def _tick_account(self, account_id: uuid.UUID) -> TickResult:
        with self._sf() as db:
            return self.runner.tick(db, account_id)

    def _heartbeat(self, results: list[TickResult]) -> None:
        failing = [r for r in results if not r.ok]
        detail = (
            f"{len(results)} account(s); "
            + (
                "all healthy"
                if not failing
                else f"{len(failing)} with problems: {failing[0].detail}"
            )
        )[:500]
        with self._sf() as db:
            db.execute(
                update(SystemState)
                .where(SystemState.id == 1)
                .values(
                    engine_heartbeat_at=utcnow(),
                    engine_detail=detail,
                    engine_degraded=bool(failing),
                )
            )
            db.commit()

    def _notify_error(self, message: str) -> None:
        try:
            with self._sf() as db:
                notify(db, "system.error", message)
        except Exception:
            logger.exception("could not record system error notification")

    def tick_once(self) -> list[TickResult]:
        """Run one synchronous cycle (tests and CLI)."""
        return self.run_cycle()

    def wait(self, timeout: float) -> None:
        with contextlib.suppress(TimeoutError):
            self._stop.wait(timeout)
