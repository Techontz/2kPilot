"""Strategy catalogue for the dashboard, and parameter validation.

Strategy *implementations* live in `strategy_engine` (code). Laravel stores
strategies, immutable versions and assignments; it asks the engine to
validate parameters because only the engine knows each strategy's schema.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.core.errors import NotFoundError, UnprocessableError
from fxrobot.db.types import utcnow
from fxrobot.models import Strategy, StrategyVersion
from fxrobot.strategy_engine import get_strategy, list_strategies
from fxrobot.strategy_engine.rules import RuleSet, RuleSetError, catalog_json

# Advanced built-ins registered from code (rule templates are seeded by Laravel).
BUILTIN_DETAILS: dict[str, dict[str, Any]] = {
    "trend_pullback": {
        "slug": "trend-pullback",
        "summary": "Advanced: trade with the higher-timeframe trend after a pullback.",
        "details": {
            "how_it_works": (
                "The H4 trend is defined by price and two EMAs. On H1 it waits for a pullback "
                "to the fast EMA that is not too deep, then for a bar confirming the trend has "
                "resumed. Stops sit beyond the recent swing."
            ),
            "struggles": (
                "Sideways markets and sharp reversals: the trend filter lags, and pullbacks "
                "can turn into reversals. Many parameters make it easy to overfit."
            ),
            "suggested_timeframe": "H1",
            "suggested_symbols": ["EURUSD", "GBPUSD", "USDJPY"],
            "suggested_contract": {"contract_family": "SPOT"},
            "difficulty": "advanced",
            "educational": True,
        },
    },
    "adaptive_trend_momentum": {
        "slug": "adaptive-trend-momentum",
        "summary": "Advanced: M15 trend regime, M5 pullback, renewed RSI momentum, ATR stop, 2:1.",
        "details": {
            "how_it_works": (
                "The M15 chart must be in a trend regime: ADX at least 25, EMA 20 above EMA 50 "
                "(below for sells) and sloping, and volatility not extreme. On M5 it waits for a "
                "pullback to EMA 20, RSI turning back up through 50 (down for sells) and a "
                "closed candle confirming the move. The stop is 1.5 × ATR, the target 2:1."
            ),
            "struggles": (
                "Choppy or range-bound markets (the regime filter then keeps it out, so it may "
                "trade rarely), sudden reversals after a pullback, and volatility spikes. On one "
                "year of real Deriv R_10/R_25 history (Oct 2025 – Oct 2026) it showed no "
                "reliable edge after costs: about break-even, with a win rate near 34 % at 2:1."
            ),
            "suggested_timeframe": "M5",
            "suggested_symbols": ["R_10", "R_25"],
            "suggested_contract": {"contract_family": "MULTIPLIER", "multiplier": 400},
            "suggested_contract_paper": {"contract_family": "SPOT"},
            "suggested_contract_note": (
                "Multipliers on Deriv (stop and target sent as money amounts), Spot on Paper. "
                "Not Rise/Fall: it has no stop loss or take profit."
            ),
            "supported_contract_families": ["SPOT", "MULTIPLIER"],
            "supported_symbols": ["R_10", "R_25"],
            "difficulty": "advanced",
            "educational": True,
            "disclaimer": (
                "Educational research strategy — not advice and not claimed to be profitable. "
                "Past results, in backtests or on demo, do not predict future results."
            ),
        },
    },
}


class StrategyConfigError(UnprocessableError):
    code = "invalid_strategy_config"


def ensure_builtin_strategies(db: Session) -> None:
    """Create a shared template (user_id NULL, version 1 = defaults) per built-in strategy.

    Users' own copies of a template share its `key` but have a user_id.
    """
    for impl in list_strategies():
        if not impl.seeds_template:
            continue
        template = select(Strategy.id).where(Strategy.key == impl.key, Strategy.user_id.is_(None))
        if db.scalar(template) is not None:
            continue
        extra = BUILTIN_DETAILS.get(impl.key, {})
        strategy = Strategy(
            key=impl.key,
            name=impl.name,
            description=impl.description,
            slug=extra.get("slug"),
            source="template",
            summary=extra.get("summary", ""),
            details=extra.get("details"),
        )
        db.add(strategy)
        db.flush()
        db.add(
            StrategyVersion(
                strategy_id=strategy.id,
                version=1,
                code_version=impl.code_version,
                parameters=impl.default_params(),
                notes="Default research parameters",
                created_at=utcnow(),
            )
        )
    db.commit()


def catalog() -> list[dict[str, Any]]:
    """Every implementation with its parameter JSON schema and defaults."""
    return [
        {
            "key": impl.key,
            "name": impl.name,
            "code_version": impl.code_version,
            "description": impl.description,
            "parameter_schema": impl.Params.model_json_schema(),
            "defaults": impl.default_params(),
            # None = no restriction.
            "contract_families": (
                None
                if impl.contract_families is None
                else [f.value for f in impl.contract_families]
            ),
            "symbols": None if impl.symbols is None else list(impl.symbols),
        }
        for impl in list_strategies()
    ]


def rules_catalog(*, ai_drafting_available: bool) -> dict[str, Any]:
    """What the visual builder (and the drafting prompt) may use."""
    return catalog_json(ai_drafting_available)


def validate_params(key: str, params: dict[str, Any]) -> dict[str, Any]:
    """Normalised parameters (+ a plain-English summary for rule sets) or a 422.

    Rule-set problems come back one per line in `details.problems`.
    """
    try:
        impl = get_strategy(key)
    except KeyError as exc:
        raise NotFoundError(f"Unknown strategy {key!r}") from exc
    try:
        parsed = impl.parse_params(params)
    except RuleSetError as exc:
        raise StrategyConfigError(
            "This strategy has problems: " + "; ".join(exc.problems),
            details={"problems": exc.problems},
        ) from exc
    except ValueError as exc:
        raise StrategyConfigError(f"Invalid parameters: {exc}") from exc
    out: dict[str, Any] = {
        "parameters": parsed.model_dump(mode="json"),
        "code_version": impl.code_version,
        "rules_text": None,
        "notes": [],
    }
    if isinstance(parsed, RuleSet):
        out["rules_text"] = parsed.to_text()
        out["notes"] = parsed.notes()
        out["warmup_bars"] = parsed.warmup_bars()
    return out
