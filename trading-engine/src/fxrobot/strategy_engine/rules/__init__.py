"""Rule-based strategies: a declarative, versioned rule format (no code
execution), its catalogue for the builder, evaluation with plain-English
explanations, and the `rules` strategy that runs it."""

from fxrobot.strategy_engine.rules.catalog import catalog_json
from fxrobot.strategy_engine.rules.model import RuleSet, RuleSetError, parse_rule_set
from fxrobot.strategy_engine.rules.strategy import RulesStrategy

__all__ = ["RuleSet", "RuleSetError", "RulesStrategy", "catalog_json", "parse_rule_set"]
