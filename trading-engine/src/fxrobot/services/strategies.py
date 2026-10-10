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
