"""Trading statistics from closed trades and an equity curve. Pure functions.

Definitions (also shown in the UI glossary):
* win rate      = winning trades / trades
* expectancy    = average net P/L per trade (money); expectancy_r in R-multiples
* profit factor = gross profit / gross loss (None when there are no losses)
* max drawdown  = largest peak-to-trough fall of the equity curve
* avg R:R       = average win / |average loss|
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class TradeStat:
    net_pnl: Decimal
    entry_time: datetime
    exit_time: datetime
    symbol: str
    side: str
    session: str
    r_multiple: Decimal | None = None
    costs: Decimal = Decimal(0)
    strategy: str | None = None


def _f(value: Decimal | float | None, places: int = 2) -> float | None:
    return None if value is None else round(float(value), places)


def _streaks(results: Sequence[bool | None]) -> tuple[int, int]:
    """Longest win / loss streaks. None (a breakeven trade) ends any streak."""
    best_win = best_loss = cur = 0
    last: bool | None = None
    for won in results:
        if won is None:
            cur, last = 0, None
            continue
        cur = cur + 1 if won == last else 1
        last = won
        if won:
            best_win = max(best_win, cur)
        else:
            best_loss = max(best_loss, cur)
    return best_win, best_loss


def drawdown_curve(
    points: Sequence[tuple[datetime, Decimal]],
) -> tuple[list[dict[str, Any]], Decimal, Decimal]:
    """Returns (curve, max drawdown amount, max drawdown %)."""
    peak = None
    max_amt = Decimal(0)
    max_pct = Decimal(0)
    curve = []
    for moment, equity in points:
        peak = equity if peak is None or equity > peak else peak
        amt = peak - equity
        pct = amt / peak * 100 if peak > 0 else Decimal(0)
        max_amt, max_pct = max(max_amt, amt), max(max_pct, pct)
        curve.append({"t": moment.isoformat(), "dd": _f(-pct, 3)})
    return curve, max_amt, max_pct


def downsample(points: Sequence[Any], limit: int = 1500) -> list[Any]:
    if len(points) <= limit:
        return list(points)
    step = len(points) / limit
    picked = [points[int(i * step)] for i in range(limit)]
    picked[-1] = points[-1]
    return picked


def group_stats(trades: Iterable[TradeStat], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[TradeStat]] = defaultdict(list)
    for t in trades:
        groups[str(getattr(t, key) or "—")].append(t)
    out = []
    for name, items in sorted(groups.items()):
        wins = [t for t in items if t.net_pnl > 0]
        gp = sum((t.net_pnl for t in wins), Decimal(0))
        gl = -sum((t.net_pnl for t in items if t.net_pnl < 0), Decimal(0))
        out.append(
            {
                "key": name,
                "trades": len(items),
                "wins": len(wins),
                "win_rate": _f(Decimal(len(wins)) / len(items) * 100, 1),
                "net_pnl": _f(sum((t.net_pnl for t in items), Decimal(0))),
                "profit_factor": _f(gp / gl) if gl > 0 else None,
            }
        )
    return out


def monthly(trades: Iterable[TradeStat], starting: Decimal) -> list[dict[str, Any]]:
    by_month: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    for t in sorted(trades, key=lambda x: x.exit_time):
        month = t.exit_time.strftime("%Y-%m")
        by_month[month] += t.net_pnl
        counts[month] += 1
    balance = starting
    out = []
    for month in sorted(by_month):
        pnl = by_month[month]
        out.append(
            {
                "month": month,
                "net_pnl": _f(pnl),
                "trades": counts[month],
                "return_pct": _f(pnl / balance * 100) if balance > 0 else None,
            }
        )
        balance += pnl
    return out


def compute(
    trades: Sequence[TradeStat],
    starting_balance: Decimal,
    equity_points: Sequence[tuple[datetime, Decimal]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: t.exit_time)
    net = sum((t.net_pnl for t in ordered), Decimal(0))
    wins = [t for t in ordered if t.net_pnl > 0]
    losses = [t for t in ordered if t.net_pnl < 0]
    gross_profit = sum((t.net_pnl for t in wins), Decimal(0))
    gross_loss = -sum((t.net_pnl for t in losses), Decimal(0))
    n = len(ordered)
    avg_win = gross_profit / len(wins) if wins else None
    avg_loss = -gross_loss / len(losses) if losses else None
    rs = [t.r_multiple for t in ordered if t.r_multiple is not None]
    best_w, best_l = _streaks([None if t.net_pnl == 0 else t.net_pnl > 0 for t in ordered])
    if equity_points is None:
        running = starting_balance
        equity_points = [(ordered[0].entry_time, starting_balance)] if ordered else []
        for t in ordered:
            running += t.net_pnl
            equity_points.append((t.exit_time, running))
    dd_curve, dd_amt, dd_pct = drawdown_curve(equity_points)
    holding = [(t.exit_time - t.entry_time).total_seconds() / 3600 for t in ordered]
    ending = starting_balance + net
    return {
        "starting_balance": _f(starting_balance),
        "ending_balance": _f(ending),
        "net_pnl": _f(net),
        "return_pct": _f(net / starting_balance * 100) if starting_balance > 0 else None,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "win_rate": _f(Decimal(len(wins)) / n * 100, 1) if n else None,
        "avg_win": _f(avg_win),
        "avg_loss": _f(avg_loss),
        "largest_win": _f(max((t.net_pnl for t in wins), default=None)),
        "largest_loss": _f(min((t.net_pnl for t in losses), default=None)),
        "expectancy": _f(net / n) if n else None,
        "expectancy_r": _f(sum(rs, Decimal(0)) / len(rs), 3) if rs else None,
        "profit_factor": _f(gross_profit / gross_loss) if gross_loss > 0 else None,
        "gross_profit": _f(gross_profit),
        "gross_loss": _f(gross_loss),
        "avg_rr": _f(avg_win / -avg_loss) if avg_win and avg_loss else None,
        "max_consecutive_wins": best_w,
        "max_consecutive_losses": best_l,
        "longest_losing_streak": best_l,
        "max_drawdown": _f(dd_amt),
        "max_drawdown_pct": _f(dd_pct),
        "total_costs": _f(sum((t.costs for t in ordered), Decimal(0))),
        "avg_holding_hours": round(sum(holding) / len(holding), 1) if holding else None,
        "equity_curve": [
            {"t": m.isoformat(), "equity": _f(e)} for m, e in downsample(equity_points)
        ],
        "drawdown_curve": downsample(dd_curve),
        "monthly": monthly(ordered, starting_balance),
        "by_symbol": group_stats(ordered, "symbol"),
        "by_session": group_stats(ordered, "session"),
        "by_side": group_stats(ordered, "side"),
        "by_strategy": group_stats(ordered, "strategy"),
    }


SUMMARY_KEYS = (
    "net_pnl",
    "return_pct",
    "trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "expectancy_r",
    "max_drawdown_pct",
    "avg_rr",
)


def summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: metrics.get(k) for k in SUMMARY_KEYS}
