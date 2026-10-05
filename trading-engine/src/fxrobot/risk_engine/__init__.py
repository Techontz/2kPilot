"""Risk engine — the final authority over every trade.

No strategy, adapter or API path can reach the execution engine without an
approved `RiskDecision`. Every rule's outcome is recorded; any failure rejects
the trade with a stored, human-readable reason. When information is missing
or uncertain, the rule FAILS (the safest outcome wins).
"""

from fxrobot.risk_engine.engine import RiskContext, RiskDecision, RuleResult, evaluate
from fxrobot.risk_engine.limits import DEFAULT_LIMITS, RiskLimits

__all__ = ["DEFAULT_LIMITS", "RiskContext", "RiskDecision", "RiskLimits", "RuleResult", "evaluate"]
