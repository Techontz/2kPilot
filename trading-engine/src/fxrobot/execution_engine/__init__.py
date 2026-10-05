"""Execution engine: turns APPROVED risk decisions into broker orders, safely.

Rules (tested in tests/test_execution.py and tests/test_reliability.py):
* The order intent is persisted (PENDING_SUBMIT → SUBMITTED) BEFORE the
  broker call, with a unique client_order_id sent to the broker.
* A rejection is final. A connection error before sending is FAILED.
* An uncertain outcome is marked UNKNOWN and reconciled via the broker using
  the client_order_id. It is NEVER blindly re-sent.
* While any order of an account is unresolved, that account takes no new
  entries.
"""
