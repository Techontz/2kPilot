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


class StrategyConfigError(UnprocessableError):
    code = "invalid_strategy_config"


def ensure_builtin_strategies(db: Session) -> None:
    """Create a catalogue row (with version 1 = defaults) for each built-in strategy."""
    for impl in list_strategies():
        if db.scalar(select(Strategy.id).where(Strategy.key == impl.key)) is not None:
            continue
        strategy = Strategy(key=impl.key, name=impl.name, description=impl.description)
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


def validate_params(key: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        impl = get_strategy(key)
    except KeyError as exc:
        raise NotFoundError(f"Unknown strategy {key!r}") from exc
    try:
        return {
            "parameters": impl.parse_params(params).model_dump(mode="json"),
            "code_version": impl.code_version,
        }
    except ValueError as exc:
        raise StrategyConfigError(f"Invalid parameters: {exc}") from exc
