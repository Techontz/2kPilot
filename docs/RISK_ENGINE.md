# Risk engine

> Status: the **global controls are implemented** (kill switch, modes, LIVE hard lock). The per-trade risk engine is **Phase 5**.

## Authority

The risk engine sits between every signal and every order. There is no other path to the execution engine. If any rule fails, the trade is **rejected**, and the reason is stored on the signal and shown in the Journal (for example, *"Trade rejected: maximum daily loss reached."*).

## Implemented now: global trading gates

`backend/src/fxrobot/services/trading_control.py` computes `new_orders_permitted`. This is the single answer to "may anything open a trade right now?":

```
new_orders_permitted =
      NOT kill_switch_engaged
  AND NOT (mode == LIVE AND live_trading_locked)
  AND mode != BACKTEST
```

| Rule | Enforcement | Test |
|---|---|---|
| Fresh install: kill switch **engaged**, mode DEMO | migration seed and defensive recreate | `test_fresh_install_is_demo_with_kill_switch_engaged`, `test_missing_state_row_is_recreated_with_kill_switch_engaged` |
| STOP is always allowed (owner), idempotent, audited | service | `test_stop_is_idempotent_and_always_audited` |
| RESUME requires explicit `confirm: true` | schema | `test_resume_requires_explicit_confirmation` |
| Mode changes only while stopped, and never auto-resume | service | `test_mode_change_requires_trading_stopped`, `test_switch_between_backtest_and_demo` |
| LIVE refused while `LIVE_TRADING_ENABLED=false` | service | `test_live_is_refused_while_hard_locked` |
| LIVE also needs the password and the typed phrase `ENABLE LIVE TRADING` | service | `test_live_requires_password_and_phrase_even_when_unlocked` |
| DB says LIVE but the lock is on → nothing trades | status computation | `test_live_state_with_lock_reengaged_blocks_orders` |
| Viewers can't control trading | `OwnerDep` | `test_viewer_cannot_control_trading` |

**The kill switch does not close positions.** Stopping new trading and liquidating are separate actions. A liquidation policy, if one is ever added, must be separately configured and separately audited.

## Phase 5: per-trade rules

Evaluated in order. The first failure rejects the trade.

1. Global gates (above), and the account's `trading_enabled` flag
2. Account environment matches the mode (a DEMO-mode signal can't reach an account that is LIVE or UNKNOWN)
3. Stop loss present and on the correct side of entry
4. Data freshness (a stale quote rejects the trade) and broker connected
5. Session restrictions and news blackout
6. Spread ≤ max spread; slippage allowance
7. Daily, weekly and max-drawdown loss limits (from realised and unrealised equity)
8. Cooldown after N consecutive losses
9. Max trades per day, max simultaneous positions, per-symbol and total exposure
10. Position sizing: `volume = (equity × risk%) / (stop distance × pip value)`, rounded **down** to the volume step, clamped to broker min/max and the max position size. If it rounds to below the minimum, reject rather than round up

Each rule is a small pure function `(context) → Approve | Reject(reason)`, unit-tested in isolation, plus an integration test for the ordering.

## Uncertainty rule

If the execution state is uncertain (outcome unknown, broker disconnected, or equity unknown), the safest outcome wins. Reject new entries, and reconcile before retrying anything.
