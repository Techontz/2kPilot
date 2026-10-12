"""The "qualifies for demo forward testing" gate. Pure, explicit, informational.

A strategy qualifies only when every check passes:

1. Real market data — synthetic data is never evidence.
2. A meaningful out-of-sample sample: at least MIN_OOS_TRADES trades.
3. Positive out-of-sample expectancy per trade AFTER costs.
4. Stability: positive expectancy in MORE than half of the walk-forward folds
   that traded (at least MIN_FOLDS folds; a single split cannot show stability).
5. The edge is distinguishable from noise: the t-statistic of the mean
   out-of-sample R-multiple is at least MIN_T_STAT (roughly a 95 % one-sided
   test). Added after the first real-data run showed a +0.009 R "edge" passing
   checks 1–4 with t = 0.58 — a coin flip with costs is not evidence.

Passing never enables anything: it only says the evidence is strong enough to
justify watching the strategy on a DEMO account. Failing explains why.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MIN_OOS_TRADES = 100
MIN_FOLDS = 3
MIN_T_STAT = 2.0


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def demo_forward_gate(
    oos: dict[str, Any],
    folds: Sequence[dict[str, Any]] | None,
    *,
    synthetic: bool,
) -> dict[str, Any]:
    """`oos` = out-of-sample metrics (stitched); `folds` = per-fold metrics
    (each with `trades` and `expectancy`), None when there were no folds."""
    trades = int(oos.get("trades") or 0)
    expectancy = oos.get("expectancy")
    checks = [
        _check(
            "Real market data",
            not synthetic,
            "synthetic data says nothing about real markets"
            if synthetic
            else "historical market data",
        ),
        _check(
            "Out-of-sample sample size",
            trades >= MIN_OOS_TRADES,
            f"{trades} out-of-sample trades (need at least {MIN_OOS_TRADES})",
        ),
        _check(
            "Positive expectancy after costs",
            expectancy is not None and expectancy > 0,
            "no out-of-sample trades"
            if expectancy is None
            else f"{expectancy:+.2f} per trade out of sample",
        ),
    ]
    if folds is None:
        checks.append(
            _check(
                "Stable across walk-forward folds",
                False,
                "run a walk-forward test: one split cannot show stability",
            )
        )
    else:
        traded = [f for f in folds if (f.get("trades") or 0) > 0]
        positive = sum(1 for f in traded if (f.get("expectancy") or 0) > 0)
        stable = len(traded) >= MIN_FOLDS and positive * 2 > len(traded)
        checks.append(
            _check(
                "Stable across walk-forward folds",
                stable,
                f"positive expectancy in {positive} of {len(traded)} folds that traded "
                f"(need more than half, and at least {MIN_FOLDS} folds)",
            )
        )
    t = oos.get("expectancy_r_tstat")
    checks.append(
        _check(
            "Edge distinguishable from noise",
            t is not None and t >= MIN_T_STAT,
            "not enough trades to measure"
            if t is None
            else f"t-statistic of the mean R is {t:.2f} (need at least {MIN_T_STAT:g})",
        )
    )
    qualifies = all(c["passed"] for c in checks)
    return {
        "qualifies_for_demo_forward_testing": qualifies,
        "checks": checks,
        "reasons": [c["detail"] for c in checks if not c["passed"]],
        "note": "Informational only: nothing is enabled automatically, and passing is not a "
        "claim of profitability.",
    }
