/** Human descriptions of every risk limit, grouped for the editor. */
export interface LimitMeta {
  key: string;
  label: string;
  help: string;
  unit?: string;
  kind: "decimal" | "int" | "sessions";
  optional: boolean;
}

export const LIMIT_GROUPS: { title: string; items: LimitMeta[] }[] = [
  {
    title: "Per trade",
    items: [
      { key: "risk_per_trade_pct", label: "Risk per trade", unit: "% of equity", help: "How much a single trade may lose if its stop loss is hit. Position size is calculated from this.", kind: "decimal", optional: false },
      { key: "max_position_lots", label: "Max position size", unit: "lots", help: "Upper cap on any single position, whatever the sizing formula says.", kind: "decimal", optional: true },
      { key: "min_stop_pips", label: "Min stop distance", unit: "pips", help: "Stops closer than this are usually hit by normal noise.", kind: "decimal", optional: true },
      { key: "max_stop_pips", label: "Max stop distance", unit: "pips", help: "Very wide stops mean tiny positions and slow capital use.", kind: "decimal", optional: true },
      { key: "min_reward_risk", label: "Min reward/risk", unit: ": 1", help: "Target must be at least this many times the stop distance.", kind: "decimal", optional: true },
    ],
  },
  {
    title: "Loss limits",
    items: [
      { key: "max_daily_loss_pct", label: "Max daily loss", unit: "%", help: "No new trades for the rest of the UTC day once reached (open P/L included).", kind: "decimal", optional: true },
      { key: "max_weekly_loss_pct", label: "Max weekly loss", unit: "%", help: "No new trades for the rest of the week once reached.", kind: "decimal", optional: true },
      { key: "max_drawdown_pct", label: "Max drawdown", unit: "%", help: "If equity falls this far from its peak, trading on the account is disabled until you review it.", kind: "decimal", optional: true },
      { key: "cooldown_after_losses", label: "Cooldown after losses", unit: "losses in a row", help: "Pause after this many consecutive losing trades…", kind: "int", optional: true },
      { key: "cooldown_minutes", label: "Cooldown length", unit: "minutes", help: "…for this long.", kind: "int", optional: true },
    ],
  },
  {
    title: "Exposure",
    items: [
      { key: "max_open_positions", label: "Max open positions", help: "Across all strategies on the account.", kind: "int", optional: true },
      { key: "max_positions_per_symbol", label: "Max per symbol", help: "Prevents stacking trades on one pair.", kind: "int", optional: true },
      { key: "max_total_exposure_lots", label: "Max total lots", unit: "lots", help: "Sum of all open position sizes.", kind: "decimal", optional: true },
      { key: "max_total_risk_pct", label: "Max total open risk", unit: "% of equity", help: "Sum of what all open trades would lose at their stops.", kind: "decimal", optional: true },
      { key: "max_trades_per_day", label: "Max trades per day", help: "Stops a malfunctioning strategy from over-trading.", kind: "int", optional: true },
    ],
  },
  {
    title: "Execution & data",
    items: [
      { key: "max_spread_pips", label: "Max spread", unit: "pips", help: "Skip entries when trading costs are unusually high.", kind: "decimal", optional: true },
      { key: "max_slippage_pips", label: "Max slippage", unit: "pips", help: "Sent to the broker as the maximum price deviation for market orders.", kind: "decimal", optional: true },
      { key: "max_data_age_seconds", label: "Max price age", unit: "seconds", help: "Reject trades when the latest price is older than this (stale data).", kind: "int", optional: false },
      { key: "allowed_sessions", label: "Allowed sessions", help: "Only open trades during these sessions (UTC).", kind: "sessions", optional: false },
    ],
  },
];

export const SESSIONS = [
  { key: "ASIA", label: "Asia 21:00–07:00" },
  { key: "LONDON", label: "London 07:00–12:00" },
  { key: "OVERLAP", label: "London+NY 12:00–16:00" },
  { key: "NEW_YORK", label: "New York 16:00–21:00" },
];
