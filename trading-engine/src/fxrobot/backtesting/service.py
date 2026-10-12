"""Backtest jobs: single runs, in/out-of-sample splits, walk-forward, sensitivity.

Runs execute on a background thread pool and store their results in MySQL.
Nothing here ever labels a strategy "profitable": validation reports show the
evidence (and its weaknesses) and leave the judgement to the user.
"""

from __future__ import annotations

import itertools
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from fxrobot.analytics import metrics as metrics_mod
from fxrobot.backtesting.engine import (
    BacktestConfig,
    Backtester,
    BacktestError,
    CostModel,
    expiry_bars,
)
from fxrobot.backtesting.validation import demo_forward_gate
from fxrobot.core.errors import NotFoundError, UnprocessableError
from fxrobot.db.types import utcnow
from fxrobot.domain.contracts import ContractFamily, ContractSpec
from fxrobot.domain.market import Candle, SymbolInfo, Timeframe
from fxrobot.domain.trading import BacktestKind, BacktestStatus, DataSource
from fxrobot.market_data import store
from fxrobot.market_data.sessions import calendar_span
from fxrobot.market_data.synthetic import DEFAULT_SPECS
from fxrobot.models import Backtest, BacktestTrade, Dataset, StrategyVersion
from fxrobot.notifications.service import notify
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.strategy_engine import get_strategy

logger = logging.getLogger(__name__)

MAX_GRID = 16
MIN_TRADES_FOR_CONFIDENCE = 30


class BacktestRequestError(UnprocessableError):
    code = "invalid_backtest"


@dataclass
class BacktestRequest:
    mode: str  # single | split | walk_forward | sensitivity
    strategy_key: str
    parameters: dict[str, Any]
    dataset_id: uuid.UUID
    start: datetime
    end: datetime
    initial_capital: Decimal
    risk: dict[str, Any]
    costs: dict[str, Any]
    strategy_version_id: uuid.UUID | None = None
    name: str = ""
    split_ratio: float = 0.7
    train_months: int = 6
    test_months: int = 2
    grid: dict[str, list[Any]] = field(default_factory=dict)
    contract: dict[str, Any] = field(default_factory=dict)  # canonical spec; {} = SPOT
    payout_ratio: Decimal = Decimal("0.95")  # Rise/Fall estimate
    commission_pct: Decimal = Decimal(0)  # Multipliers estimate


# Deriv synthetic indices trade around the clock (no FX weekend).
SYNTHETIC_PREFIXES = ("R_", "1HZ", "BOOM", "CRASH", "JD", "RDB", "stpRNG")


def symbol_spec(symbol: str, candles: list[Candle]) -> SymbolInfo:
    spec = DEFAULT_SPECS.get(symbol)
    if spec is not None:
        return spec.symbol_info()
    if symbol.startswith(SYNTHETIC_PREFIXES):
        return index_spec(symbol, candles)
    raise BacktestRequestError(
        f"No contract specification for {symbol}; supported: "
        f"{', '.join(sorted(DEFAULT_SPECS))} and Deriv synthetic indices (R_10 … 1HZ100V)"
    )


def index_spec(symbol: str, candles: list[Candle]) -> SymbolInfo:
    """A 24/7 index quoted in USD (e.g. data downloaded from Deriv for R_100)."""
    digits = 2
    for candle in candles[:500]:
        exponent = candle.close.normalize().as_tuple().exponent
        if isinstance(exponent, int):
            digits = max(digits, min(6, -exponent))
    point = Decimal(1).scaleb(-digits)
    return SymbolInfo(
        name=symbol,
        description=f"{symbol} (synthetic index)",
        base_currency=symbol,
        quote_currency="USD",
        digits=digits,
        point=point,
        contract_size=Decimal(1),
        volume_min=Decimal("0.01"),
        volume_max=Decimal(1000),
        volume_step=Decimal("0.01"),
        trade_allowed=True,
        canonical=symbol,
        category="synthetic",
        market_open=True,
    )


def cost_model(raw: dict[str, Any]) -> CostModel:
    def dec(key: str, default: str | None) -> Decimal | None:
        value = raw.get(key, default)
        return None if value in (None, "") else Decimal(str(value))

    try:
        model = CostModel(
            spread_pips=dec("spread_pips", None),
            commission_per_lot=dec("commission_per_lot", "3.5") or Decimal(0),
            slippage_pips=dec("slippage_pips", "0.2") or Decimal(0),
            swap_long_per_lot=dec("swap_long_per_lot", "0") or Decimal(0),
            swap_short_per_lot=dec("swap_short_per_lot", "0") or Decimal(0),
        )
    except (ArithmeticError, ValueError) as exc:
        raise BacktestRequestError(f"Invalid cost settings: {exc}") from exc
    if any(
        v is not None and v < 0
        for v in (model.spread_pips, model.commission_per_lot, model.slippage_pips)
    ):
        raise BacktestRequestError("Costs cannot be negative")
    return model


def _warmup(strategy_key: str, params: dict[str, Any]) -> timedelta:
    strategy = get_strategy(strategy_key)
    p = strategy.parse_params(params)
    return max(calendar_span(tf.seconds, n) for tf, n in strategy.required_bars(p).items())


class BacktestService:
    def __init__(self, session_factory: sessionmaker[Session], workers: int = 1) -> None:
        self._sf = session_factory
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fx-backtest")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ── creation ─────────────────────────────────────────────────────────
    def create(
        self,
        db: Session,
        req: BacktestRequest,
        user_id: uuid.UUID,
        *,
        run_async: bool = True,
    ) -> Backtest:
        try:
            strategy = get_strategy(req.strategy_key) if req.strategy_key else None
        except KeyError:
            strategy = None
        if strategy is None:
            raise BacktestRequestError("Unknown strategy")
        try:
            params = strategy.parse_params(req.parameters).model_dump(mode="json")
        except ValueError as exc:
            raise BacktestRequestError(f"Invalid strategy parameters: {exc}") from exc
        try:
            limits = RiskLimits.from_mapping(req.risk)
        except (ValueError, ArithmeticError) as exc:
            raise BacktestRequestError(f"Invalid risk settings: {exc}") from exc
        costs = cost_model(req.costs)
        try:
            contract = ContractSpec.parse(req.contract)
        except ValueError as exc:
            raise BacktestRequestError(f"Invalid contract settings: {exc}") from exc
        if not Decimal("0.01") <= req.payout_ratio <= Decimal(2):
            raise BacktestRequestError("payout_ratio must be between 0.01 and 2")
        if not Decimal(0) <= req.commission_pct <= Decimal(10):
            raise BacktestRequestError("commission_pct must be between 0 and 10")
        dataset = db.get(Dataset, req.dataset_id)
        if dataset is None:
            raise NotFoundError("Dataset not found")
        problem = strategy.support_problem(dataset.symbol, contract.contract_family)
        if problem is not None:
            raise BacktestRequestError(problem)
        if contract.contract_family is ContractFamily.RISE_FALL:
            try:
                expiry_bars(contract, dataset.timeframe)
            except BacktestError as exc:
                raise BacktestRequestError(str(exc)) from exc
        if req.end <= req.start:
            raise BacktestRequestError("End must be after start")
        if req.initial_capital <= 0:
            raise BacktestRequestError("Initial capital must be positive")
        if req.mode not in ("single", "split", "walk_forward", "sensitivity"):
            raise BacktestRequestError("mode must be single, split, walk_forward or sensitivity")
        grid = (
            self._validate_grid(strategy.key, params, req.grid)
            if req.mode in ("walk_forward", "sensitivity")
            else {}
        )
        if req.mode == "sensitivity" and not grid:
            raise BacktestRequestError("Sensitivity analysis needs at least one parameter range")
        if req.mode == "split" and not 0.3 <= req.split_ratio <= 0.9:
            raise BacktestRequestError("split_ratio must be between 0.3 and 0.9")
        kind = {
            "single": BacktestKind.SINGLE,
            "split": BacktestKind.SPLIT,
            "walk_forward": BacktestKind.WALK_FORWARD,
            "sensitivity": BacktestKind.SENSITIVITY,
        }[req.mode]
        row = Backtest(
            kind=kind,
            name=(req.name or f"{strategy.name} · {dataset.symbol} {dataset.timeframe}")[:200],
            status=BacktestStatus.QUEUED,
            strategy_key=strategy.key,
            strategy_version_id=req.strategy_version_id,
            code_version=strategy.code_version,
            parameters=params,
            symbol=dataset.symbol,
            timeframe=dataset.timeframe,
            dataset_id=dataset.id,
            data_source=dataset.source.value,
            start=req.start,
            end=req.end,
            initial_capital=req.initial_capital,
            account_currency="USD",
            risk_settings=limits.as_json(),
            costs=costs.as_json(),
            config={
                "split_ratio": req.split_ratio,
                "train_months": req.train_months,
                "test_months": req.test_months,
                "grid": grid,
                "contract": contract.as_json(),
                "payout_ratio": str(req.payout_ratio),
                "payout_ratio_is_estimate": contract.contract_family is ContractFamily.RISE_FALL,
                "commission_pct": str(req.commission_pct),
            },
            user_id=user_id,
            created_at=utcnow(),
        )
        db.add(row)
        db.commit()
        if run_async:
            self._pool.submit(self.execute, row.id)
        return row

    @staticmethod
    def _validate_grid(
        key: str, params: dict[str, Any], grid: dict[str, list[Any]]
    ) -> dict[str, list[Any]]:
        strategy = get_strategy(key)
        clean = {k: list(v) for k, v in grid.items() if v}
        unknown = [k for k in clean if k not in params]
        if unknown:
            raise BacktestRequestError(f"Unknown parameters in grid: {', '.join(unknown)}")
        if len(clean) > 2:
            raise BacktestRequestError("Vary at most two parameters at a time")
        combos = list(itertools.product(*clean.values())) if clean else []
        if len(combos) > MAX_GRID:
            raise BacktestRequestError(f"Grid too large ({len(combos)} runs, max {MAX_GRID})")
        for combo in combos:
            try:
                strategy.parse_params({**params, **dict(zip(clean, combo, strict=True))})
            except ValueError as exc:
                raise BacktestRequestError(f"Invalid grid value {combo}: {exc}") from exc
        return clean

    # ── execution ────────────────────────────────────────────────────────
    def execute(self, backtest_id: uuid.UUID) -> None:
        with self._sf() as db:
            row = db.get(Backtest, backtest_id)
            if row is None:
                return
            row.status, row.started_at, row.progress = BacktestStatus.RUNNING, utcnow(), 0
            db.commit()
            try:
                candles = self._candles(db, row)
                handler: dict[BacktestKind, Callable[[Session, Backtest, list[Candle]], None]] = {
                    BacktestKind.SINGLE: self._single,
                    BacktestKind.SPLIT: self._split,
                    BacktestKind.WALK_FORWARD: self._walk_forward,
                    BacktestKind.SENSITIVITY: self._sensitivity,
                }
                handler[row.kind](db, row, candles)
                row.status, row.progress, row.finished_at = BacktestStatus.COMPLETED, 100, utcnow()
                db.commit()
                ret = (row.metrics or {}).get("return_pct")
                notify(
                    db,
                    "backtest.completed",
                    f"{row.name}: {(row.metrics or {}).get('trades', 0)} trades, return {ret}% "
                    "(historical — not a guarantee of future results).",
                    data={"backtest_id": str(row.id)},
                )
            except (BacktestError, BacktestRequestError, ValueError) as exc:
                self._fail(db, row, str(exc))
            except Exception as exc:
                logger.exception("backtest %s crashed", backtest_id)
                self._fail(db, row, f"Internal error: {exc.__class__.__name__}")

    def _fail(self, db: Session, row: Backtest, message: str) -> None:
        db.rollback()
        row.status, row.error, row.finished_at = BacktestStatus.FAILED, message[:2000], utcnow()
        db.commit()
        notify(db, "backtest.failed", f"{row.name}: {message}", data={"backtest_id": str(row.id)})

    def _candles(self, db: Session, row: Backtest) -> list[Candle]:
        if row.dataset_id is None:
            raise BacktestError("Dataset was deleted")
        warm = _warmup(row.strategy_key, row.parameters)
        candles = store.load_candles(db, row.dataset_id, row.start - warm, row.end)
        dataset = db.get(Dataset, row.dataset_id)
        row.data_checksum = store.checksum(candles)
        if dataset is not None and dataset.source is DataSource.SYNTHETIC:
            row.config = {**row.config, "synthetic_data": True}
        if not [c for c in candles if c.time >= row.start]:
            raise BacktestError("The dataset has no bars inside the selected date range")
        return candles

    def _run(
        self,
        row: Backtest,
        candles: list[Candle],
        params: dict[str, Any],
        start: datetime,
        end: datetime,
        progress: Callable[[int], None] | None = None,
    ) -> Any:
        cfg = BacktestConfig(
            strategy_key=row.strategy_key,
            params=params,
            symbol=symbol_spec(row.symbol, candles),
            start=start,
            end=end,
            initial_capital=row.initial_capital,
            limits=RiskLimits.from_mapping(row.risk_settings),
            costs=cost_model(row.costs),
            contract=ContractSpec.parse(row.config.get("contract")),
            payout_ratio=Decimal(str(row.config.get("payout_ratio", "0.95"))),
            commission_pct=Decimal(str(row.config.get("commission_pct", "0"))),
        )
        return Backtester(cfg, candles, row.timeframe).run(progress)

    def _progress(self, db: Session, row: Backtest, lo: int, hi: int) -> Callable[[int], None]:
        def update(pct: int) -> None:
            value = lo + int((hi - lo) * pct / 100)
            if value != row.progress:
                row.progress = value
                db.commit()

        return update

    def _store_trades(self, db: Session, row: Backtest, result: Any) -> None:
        for t in result.trades:
            db.add(
                BacktestTrade(
                    backtest_id=row.id,
                    symbol=row.symbol,
                    side=t.side,
                    signal_time=t.signal_time,
                    entry_time=t.entry_time,
                    entry_price=t.entry_price,
                    exit_time=t.exit_time,
                    exit_price=t.exit_price,
                    exit_reason=t.exit_reason,
                    volume=t.volume,
                    stop_loss=t.stop_loss,
                    take_profit=t.take_profit,
                    risk_amount=t.risk_amount,
                    contract_type=t.contract_type.value if t.contract_type else None,
                    stake=t.stake,
                    payout=t.payout,
                    outcome=t.outcome,
                    gross_pnl=t.gross_pnl,
                    costs=t.costs,
                    net_pnl=t.net_pnl,
                    r_multiple=t.r_multiple,
                    session=t.session,
                    regime=t.regime,
                    reasons=t.reasons,
                )
            )

    def _child(
        self,
        db: Session,
        parent: Backtest,
        kind: BacktestKind,
        name: str,
        params: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> Backtest:
        child = Backtest(
            parent_id=parent.id,
            kind=kind,
            name=name[:200],
            status=BacktestStatus.RUNNING,
            strategy_key=parent.strategy_key,
            strategy_version_id=parent.strategy_version_id,
            code_version=parent.code_version,
            parameters=params,
            symbol=parent.symbol,
            timeframe=parent.timeframe,
            dataset_id=parent.dataset_id,
            data_source=parent.data_source,
            data_checksum=parent.data_checksum,
            start=start,
            end=end,
            initial_capital=parent.initial_capital,
            account_currency=parent.account_currency,
            risk_settings=parent.risk_settings,
            costs=parent.costs,
            config={
                k: v
                for k, v in parent.config.items()
                if k in ("contract", "payout_ratio", "payout_ratio_is_estimate", "commission_pct")
            },
            user_id=parent.user_id,
            created_at=utcnow(),
            started_at=utcnow(),
        )
        db.add(child)
        db.flush()
        return child

    def _finish_child(self, db: Session, child: Backtest, result: Any, store_trades: bool) -> None:
        child.metrics = result.metrics
        child.status, child.progress, child.finished_at = BacktestStatus.COMPLETED, 100, utcnow()
        if store_trades:
            self._store_trades(db, child, result)
        db.commit()

    # ── modes ────────────────────────────────────────────────────────────
    def _single(self, db: Session, row: Backtest, candles: list[Candle]) -> None:
        result = self._run(
            row, candles, row.parameters, row.start, row.end, self._progress(db, row, 0, 99)
        )
        row.metrics = result.metrics
        row.report = {"warnings": warnings_for(result.metrics, row), "notes": result.notes}
        self._store_trades(db, row, result)
        db.commit()

    def _split(self, db: Session, row: Backtest, candles: list[Candle]) -> None:
        ratio = float(row.config.get("split_ratio", 0.7))
        cut = row.start + (row.end - row.start) * ratio
        cut = Timeframe.D1.floor(cut)
        is_row = self._child(
            db, row, BacktestKind.IN_SAMPLE, "In-sample", row.parameters, row.start, cut
        )
        is_res = self._run(
            row, candles, row.parameters, row.start, cut, self._progress(db, row, 0, 50)
        )
        self._finish_child(db, is_row, is_res, True)
        oos_row = self._child(
            db, row, BacktestKind.OUT_OF_SAMPLE, "Out-of-sample", row.parameters, cut, row.end
        )
        oos_res = self._run(
            row, candles, row.parameters, cut, row.end, self._progress(db, row, 50, 99)
        )
        self._finish_child(db, oos_row, oos_res, True)
        row.metrics = oos_res.metrics
        comparison = compare(is_res.metrics, oos_res.metrics)
        row.report = {
            "split_at": cut.isoformat(),
            "in_sample": metrics_mod.summary(is_res.metrics),
            "out_of_sample": metrics_mod.summary(oos_res.metrics),
            **comparison,
            "warnings": comparison["warnings"] + warnings_for(oos_res.metrics, row),
            "validation": demo_forward_gate(oos_res.metrics, None, synthetic=is_synthetic(row)),
        }
        db.commit()

    def _walk_forward(self, db: Session, row: Backtest, candles: list[Candle]) -> None:
        train = timedelta(days=30 * int(row.config.get("train_months", 6)))
        test = timedelta(days=30 * int(row.config.get("test_months", 2)))
        grid = row.config.get("grid") or {}
        combos = [dict(zip(grid, c, strict=True)) for c in itertools.product(*grid.values())] or [
            {}
        ]
        windows = walk_forward_windows(row.start, row.end, train, test)
        if not windows:
            raise BacktestError("Date range too short for one train+test window")
        oos_trades: list[metrics_mod.TradeStat] = []
        table: list[dict[str, Any]] = []
        for n, (t0, t1, t2) in enumerate(windows, start=1):
            best, best_score, best_is = row.parameters, None, None
            for combo in combos:
                params = {**row.parameters, **combo}
                res = self._run(row, candles, params, t0, t1)
                score = res.metrics.get("expectancy_r")
                if (
                    res.metrics["trades"] >= 10
                    and score is not None
                    and (best_score is None or score > best_score)
                ):
                    best, best_score, best_is = params, score, res.metrics
            child = self._child(
                db, row, BacktestKind.WALK_FORWARD_WINDOW, f"Window {n}", best, t1, t2
            )
            res = self._run(row, candles, best, t1, t2)
            self._finish_child(db, child, res, True)
            oos_trades += [
                metrics_mod.TradeStat(
                    t.net_pnl,
                    t.entry_time,
                    t.exit_time,
                    row.symbol,
                    t.side.value,
                    t.session,
                    t.r_multiple,
                    t.costs,
                    regime=t.regime,
                )
                for t in res.trades
            ]
            table.append(
                {
                    "window": n,
                    "train_start": t0.isoformat(),
                    "test_start": t1.isoformat(),
                    "test_end": t2.isoformat(),
                    "chosen": {k: best.get(k) for k in grid} if grid else {},
                    "train": metrics_mod.summary(best_is) if best_is else None,
                    "test": metrics_mod.summary(res.metrics),
                }
            )
            row.progress = int(n / len(windows) * 99)
            db.commit()
        row.metrics = metrics_mod.compute(oos_trades, row.initial_capital)
        profitable = sum(1 for w in table if (w["test"].get("net_pnl") or 0) > 0)
        row.report = {
            "windows": table,
            "profitable_windows": profitable,
            "total_windows": len(table),
            "validation": demo_forward_gate(
                row.metrics, [w["test"] for w in table], synthetic=is_synthetic(row)
            ),
            "warnings": warnings_for(row.metrics, row)
            + (
                [f"Only {profitable} of {len(table)} out-of-sample windows were profitable."]
                if profitable < len(table) / 2
                else []
            ),
        }
        db.commit()

    def _sensitivity(self, db: Session, row: Backtest, candles: list[Candle]) -> None:
        grid = row.config.get("grid") or {}
        combos = [dict(zip(grid, c, strict=True)) for c in itertools.product(*grid.values())]
        results = []
        for n, combo in enumerate(combos, start=1):
            params = {**row.parameters, **combo}
            label = ", ".join(f"{k}={v}" for k, v in combo.items())
            child = self._child(
                db, row, BacktestKind.SENSITIVITY_RUN, label, params, row.start, row.end
            )
            res = self._run(row, candles, params, row.start, row.end)
            self._finish_child(db, child, res, False)
            results.append({"params": combo, **metrics_mod.summary(res.metrics)})
            row.progress = int(n / len(combos) * 99)
            db.commit()
        returns = [r["return_pct"] or 0 for r in results]
        positive = sum(1 for r in returns if r > 0)
        spread = (max(returns) - min(returns)) if returns else 0
        warnings = []
        if results and positive < len(results):
            warnings.append(
                f"Only {positive} of {len(results)} parameter combinations were profitable."
            )
        if spread > 20:
            warnings.append(
                f"Returns vary by {spread:.1f} percentage points across small parameter "
                "changes — results are fragile (a sign of overfitting)."
            )
        row.metrics = None
        row.report = {
            "grid": grid,
            "results": results,
            "profitable_share": positive / len(results) if results else 0,
            "return_spread": spread,
            "warnings": warnings,
        }
        db.commit()


def walk_forward_windows(
    start: datetime, end: datetime, train: timedelta, test: timedelta
) -> list[tuple[datetime, datetime, datetime]]:
    """Rolling (train start, test start, test end) windows; test windows never overlap."""
    windows = []
    cursor = start
    while cursor + train + test <= end + timedelta(days=1):
        windows.append((cursor, cursor + train, min(cursor + train + test, end)))
        cursor += test
    return windows


def is_synthetic(row: Backtest) -> bool:
    return bool(row.config.get("synthetic_data")) or row.data_source == DataSource.SYNTHETIC.value


def compare(is_m: dict[str, Any], oos_m: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    is_e, oos_e = is_m.get("expectancy_r"), oos_m.get("expectancy_r")
    is_pf, oos_pf = is_m.get("profit_factor"), oos_m.get("profit_factor")
    if is_e is not None and oos_e is not None and is_e > 0 >= oos_e:
        warnings.append(
            "Positive in-sample but not out-of-sample: the edge did not hold on unseen data."
        )
    if is_pf and oos_pf and oos_pf < 0.7 * is_pf:
        warnings.append(
            f"Out-of-sample profit factor fell {100 - oos_pf / is_pf * 100:.0f}% versus in-sample."
        )
    return {
        "degradation": {
            "expectancy_r": [is_e, oos_e],
            "profit_factor": [is_pf, oos_pf],
            "win_rate": [is_m.get("win_rate"), oos_m.get("win_rate")],
        },
        "warnings": warnings,
    }


def warnings_for(m: dict[str, Any], row: Backtest) -> list[str]:
    out = ["Historical results do not guarantee future performance."]
    if is_synthetic(row):
        out.insert(0, "SYNTHETIC data: these results say nothing about real markets.")
    trades = m.get("trades") or 0
    if trades < MIN_TRADES_FOR_CONFIDENCE:
        out.append(
            f"Only {trades} trades — too few for statistical confidence "
            f"(aim for {MIN_TRADES_FOR_CONFIDENCE}+)."
        )
    if (m.get("rejections") or {}).get("Max drawdown"):
        out.append("The maximum-drawdown limit halted trading during this test.")
    if row.config.get("payout_ratio_is_estimate"):
        out.append(
            f"Rise/Fall payouts are an ESTIMATE ({row.config.get('payout_ratio')} × stake per "
            "win); live payouts vary per quote and include up to 3 % app markup."
        )
    return out


def list_backtests(db: Session, limit: int = 50) -> list[Backtest]:
    return list(
        db.scalars(
            select(Backtest)
            .where(Backtest.parent_id.is_(None))
            .order_by(Backtest.created_at.desc())
            .limit(limit)
        )
    )


def version_params(db: Session, version_id: uuid.UUID) -> tuple[str, dict[str, Any]]:
    version = db.get(StrategyVersion, version_id)
    if version is None:
        raise NotFoundError("Strategy version not found")
    return version.strategy.key, version.parameters
