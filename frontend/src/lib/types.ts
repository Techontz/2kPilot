// Mirrors the backend response schemas (backend/src/fxrobot/schemas).

export type TradingMode = "BACKTEST" | "DEMO" | "LIVE";
export type UserRole = "owner" | "viewer";
export type EngineState = "offline" | "running" | "degraded";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  last_login_at: string | null;
}

export interface SessionInfo {
  user: User;
  expires_at: string;
}

export interface TradingStatus {
  trading_mode: TradingMode;
  kill_switch_engaged: boolean;
  kill_switch_reason: string | null;
  kill_switch_changed_at: string | null;
  mode_changed_at: string | null;
  live_trading_locked: boolean;
  new_orders_permitted: boolean;
  engine_state: EngineState;
  engine_detail: string;
}

export interface SystemStatus {
  app_name: string;
  version: string;
  environment: string;
  trading: TradingStatus;
  broker_accounts_connected: number;
  broker_accounts_total: number;
}

export type ConnectorStatus = "available" | "unavailable" | "planned";

export interface ConnectorField {
  name: string;
  label: string;
  secret: boolean;
  help: string;
  kind: "text" | "password" | "number" | "select" | "boolean" | "url";
  required: boolean;
  default: string | null;
  options: string[];
}

export interface Connector {
  id: "paper" | "mt5_bridge";
  name: string;
  status: ConnectorStatus;
  status_detail: string;
  environments: AccountEnvironment[];
  fields: ConnectorField[];
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  actor_label: string;
  action: string;
  outcome: "success" | "failure" | "denied";
  target_type: string | null;
  target_id: string | null;
  ip_address: string | null;
  correlation_id: string | null;
  details: Record<string, unknown>;
}

// ── Trading domain ──────────────────────────────────────────────────────
export type AccountEnvironment = "PAPER" | "DEMO" | "LIVE" | "UNKNOWN";
export type ConnectionStatus = "CONNECTED" | "DISCONNECTED" | "RECONNECTING" | "ERROR";
export type Side = "BUY" | "SELL";
export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

export interface BrokerConnection {
  id: string;
  label: string;
  connector_type: "paper" | "mt5_bridge";
  expected_environment: AccountEnvironment;
  settings: Record<string, unknown>;
  has_credentials: boolean;
  status: ConnectionStatus;
  status_detail: string | null;
  is_enabled: boolean;
  last_connected_at: string | null;
  last_error_at: string | null;
  created_at: string;
  accounts?: TradingAccount[];
}

export interface TradingAccount {
  id: string;
  connection_id: string;
  label: string;
  broker_account_id: string;
  name: string;
  server: string;
  currency: string;
  environment: AccountEnvironment;
  leverage: number | null;
  trading_enabled: boolean;
  risk_profile_id: string | null;
  balance: string | null;
  equity: string | null;
  margin: string | null;
  free_margin: string | null;
  margin_level: string | null;
  synced_at: string | null;
  connection?: BrokerConnection | null;
  open_positions?: number;
  active_strategies?: number;
  risk_profile_name?: string | null;
  connection_status?: ConnectionStatus;
  connector_type?: string;
  drawdown_pct?: number | null;
}

export interface Trade {
  id: string;
  account_id: string;
  symbol: string;
  side: Side;
  status: "OPEN" | "CLOSED";
  volume: string;
  requested_entry: string | null;
  entry_price: string;
  entry_time: string;
  stop_loss: string | null;
  take_profit: string | null;
  initial_stop_loss: string | null;
  risk_amount: string | null;
  spread_at_entry: string | null;
  slippage_pips: string | null;
  session: string | null;
  broker_position_id: string | null;
  exit_price: string | null;
  exit_time: string | null;
  exit_reason: string | null;
  gross_pnl: string | null;
  commission: string | null;
  swap: string | null;
  net_pnl: string | null;
  unrealized_pnl: string | null;
  r_multiple: string | null;
  is_simulated: boolean;
  signal_id: string | null;
  strategy_version_id: string | null;
  account_label?: string | null;
  account_environment?: AccountEnvironment | null;
  strategy?: string | null;
}

export interface OrderRow {
  id: string;
  client_order_id: string;
  account_id: string;
  signal_id: string | null;
  trade_id: string | null;
  purpose: "ENTRY" | "EXIT";
  symbol: string;
  side: Side;
  order_type: string;
  volume: string;
  filled_volume: string;
  requested_price: string | null;
  fill_price: string | null;
  stop_loss: string | null;
  take_profit: string | null;
  status: string;
  broker_order_id: string | null;
  broker_code: string | null;
  broker_message: string | null;
  attempts: number;
  is_simulated: boolean;
  created_at: string;
  submitted_at: string | null;
  filled_at: string | null;
}

export interface RiskCheck {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface StrategyCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface SignalRow {
  id: string;
  account_id: string;
  assignment_id: string | null;
  strategy_version_id: string;
  symbol: string;
  side: Side;
  timeframe: Timeframe;
  bar_time: string;
  entry_price: string;
  stop_loss: string;
  take_profit: string | null;
  reasons: string[];
  status: string;
  risk_checks: RiskCheck[];
  rejection_reason: string | null;
  volume: string | null;
  risk_amount: string | null;
  correlation_id: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface JournalEvent {
  id: number;
  occurred_at: string;
  account_id: string | null;
  signal_id: string | null;
  order_id: string | null;
  trade_id: string | null;
  event_type: string;
  message: string;
  data: Record<string, unknown>;
  correlation_id: string | null;
}

export interface NotificationItem {
  id: number;
  type: string;
  severity: "info" | "success" | "warning" | "critical";
  title: string;
  message: string;
  account_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

export interface StrategyVersion {
  id: string;
  version: number;
  code_version: string;
  parameters: Record<string, unknown>;
  notes: string;
  created_at: string;
}

export interface Evaluation {
  outcome: "SIGNAL" | "NO_SETUP" | "INSUFFICIENT_DATA";
  summary: string;
  bar_time: string;
  checks: StrategyCheck[];
}

export interface Assignment {
  id: string;
  strategy_id: string;
  symbol: string;
  status: "ENABLED" | "PAUSED";
  status_reason: string | null;
  account: { id: string; label: string; environment: AccountEnvironment; trading_enabled: boolean } | null;
  version: number | null;
  strategy_version_id: string;
  last_bar_evaluated: string | null;
  last_evaluation: Evaluation | null;
  last_signal: SignalRow | null;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  $ref?: string;
  allOf?: { $ref: string }[];
}

export interface StrategyInfo {
  id: string;
  key: string;
  name: string;
  description: string;
  code_version: string;
  timeframes: Timeframe[];
  versions: StrategyVersion[];
  parameter_schema: {
    properties: Record<string, JsonSchemaProperty>;
    $defs?: Record<string, { enum?: string[]; type?: string }>;
  };
  assignments: Assignment[];
  status: "ENABLED" | "PAUSED";
  performance: { closed_trades: number; net_pnl: string };
  last_trade: Trade | null;
  last_backtest: BacktestSummary | null;
  backtest_status: string | null;
  backtest_completed: boolean;
}

export type RiskLimits = Record<string, string | number | string[] | null>;

export interface RiskProfile {
  id: string;
  name: string;
  limits: RiskLimits;
  updated_at: string;
}

export interface Dataset {
  id: string;
  symbol: string;
  timeframe: Timeframe;
  source: "broker" | "csv" | "synthetic";
  source_ref: string;
  description: string;
  first_bar: string | null;
  last_bar: string | null;
  bar_count: number;
  gap_count: number;
  checksum: string;
  updated_at: string;
}

export interface CandlePoint {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  spread_points: number | null;
}

export interface GroupStat {
  key: string;
  trades: number;
  wins: number;
  win_rate: number | null;
  net_pnl: number | null;
  profit_factor: number | null;
}

export interface Metrics {
  starting_balance: number | null;
  ending_balance: number | null;
  net_pnl: number | null;
  return_pct: number | null;
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  largest_win: number | null;
  largest_loss: number | null;
  expectancy: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_rr: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  total_costs: number | null;
  avg_holding_hours: number | null;
  equity_curve: { t: string; equity: number | null }[];
  drawdown_curve: { t: string; dd: number | null }[];
  monthly: { month: string; net_pnl: number | null; trades: number; return_pct: number | null }[];
  by_symbol: GroupStat[];
  by_session: GroupStat[];
  by_side: GroupStat[];
  by_strategy: GroupStat[];
  signals?: number;
  evaluations?: number;
  rejections?: Record<string, number>;
}

export interface BacktestSummary {
  id: string;
  parent_id: string | null;
  kind: string;
  name: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  progress: number;
  strategy_key: string;
  code_version: string;
  symbol: string;
  timeframe: Timeframe;
  data_source: string;
  start: string;
  end: string;
  initial_capital: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  summary: Partial<Metrics> | null;
  warnings: string[];
}

export interface BacktestDetail extends BacktestSummary {
  parameters: Record<string, unknown>;
  risk_settings: RiskLimits;
  costs: Record<string, string | null>;
  config: Record<string, unknown>;
  metrics: Metrics | null;
  report: Record<string, unknown> | null;
  data_checksum: string;
  children?: BacktestDetail[];
}

export interface BacktestTradeRow {
  id: number;
  side: Side;
  signal_time: string;
  entry_time: string;
  entry_price: string;
  exit_time: string;
  exit_price: string;
  exit_reason: string;
  volume: string;
  stop_loss: string;
  take_profit: string | null;
  risk_amount: string;
  gross_pnl: string;
  costs: string;
  net_pnl: string;
  r_multiple: string;
  session: string;
  reasons: string[];
}

export interface Overview {
  accounts: TradingAccount[];
  currency: string;
  totals: {
    balance: string | null;
    equity: string | null;
    today_pnl: string | null;
    realized_today: string | null;
    open_pnl: string | null;
    open_positions: number;
    trades_today: number;
    open_risk: string | null;
    open_risk_unknown: boolean;
    max_drawdown_pct: number | null;
  };
  active_strategies: number;
  equity_series: { t: string; equity: number; balance: number }[];
  equity_series_account: string | null;
  recent_events: JournalEvent[];
}

export interface Performance extends Partial<Metrics> {
  has_data: boolean;
  simulated?: boolean;
  unrealized_pnl?: number;
  open_positions?: number;
  balance_history?: { t: string; balance: number; equity: number }[];
  daily?: { period: string; net_pnl: number; trades: number }[];
  weekly?: { period: string; net_pnl: number; trades: number }[];
  execution?: {
    orders: number;
    orders_by_status: Record<string, number>;
    fill_rate: number | null;
    avg_slippage_pips: number | null;
    worst_slippage_pips: number | null;
    avg_spread: number | null;
    avg_fill_seconds: number | null;
    unresolved_orders: number;
    signals_by_status: Record<string, number>;
    top_rejections: { reason: string; count: number }[];
  };
}

export interface ReadinessItem {
  id: string;
  label: string;
  passed: boolean;
  detail: string;
  required: boolean;
}

export interface Readiness {
  account_id: string;
  checked_at: string;
  ready: boolean;
  passed: number;
  total: number;
  items: ReadinessItem[];
  note: string;
}

export interface UsageMeter {
  amount: string;
  pct: number | null;
  limit_pct: string | null;
}

export interface RiskUsage {
  account_id: string;
  profile: RiskProfile | null;
  recent_violations: SignalRow[];
  live: boolean;
  error?: string;
  equity?: string;
  balance?: string;
  currency?: string;
  daily_loss?: UsageMeter;
  weekly_loss?: UsageMeter;
  drawdown?: UsageMeter & { peak_equity: string };
  open_risk?: UsageMeter & { unknown: boolean };
  positions?: { open: number; max: number | null; lots: string; max_lots: string | null };
  trades_today?: { count: number; max: number | null };
  consecutive_losses?: { count: number; cooldown_after: number | null };
}

export interface QuoteRow {
  symbol: string;
  bid: string;
  ask: string;
  time: string;
  spread_pips: string;
  age_seconds: number;
  digits: number;
  watched: boolean;
}
