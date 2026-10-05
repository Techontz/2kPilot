/**
 * Shapes returned by the Laravel API (backend/app/Http/Controllers/Api).
 * Money, prices and volumes arrive as DECIMAL strings — never floats — and
 * are only formatted for display (lib/format.ts).
 */

export type Decimal = string;
export type AccountEnvironment = "PAPER" | "DEMO" | "LIVE" | "UNKNOWN";
export type ConnectionStatus = "CONNECTED" | "DISCONNECTED" | "RECONNECTING" | "ERROR";
export type ConnectorType = "paper" | "deriv" | "mt5_bridge";
export type TradingMode = "BACKTEST" | "DEMO" | "LIVE";
export type EngineState = "offline" | "running" | "degraded";
export type Side = "BUY" | "SELL";
export type Severity = "info" | "success" | "warning" | "critical";

export interface User {
  id: string;
  name: string;
  email: string;
  role: "owner" | "viewer";
  mfa_enabled: boolean;
  mfa_required: boolean;
  last_login_at: string | null;
}

export interface TradingStatus {
  trading_mode: TradingMode;
  kill_switch_engaged: boolean;
  kill_switch_reason: string | null;
  kill_switch_changed_at: string | null;
  live_trading_locked: boolean;
  engine_state: EngineState;
  engine_detail: string;
  engine_heartbeat_at: string | null;
  new_orders_permitted: boolean;
}

export interface Capabilities {
  market_orders?: boolean;
  pending_orders?: boolean;
  modify_position?: boolean;
  partial_close?: boolean;
  historical_candles?: boolean;
  trade_history?: boolean;
  client_order_ids?: boolean;
  volume_unit?: "lots" | "units";
  notes?: string[];
}

export interface Account {
  id: string;
  label: string;
  broker: string;
  connector_type: ConnectorType;
  connection_id: string;
  connection_status: ConnectionStatus;
  connection_detail: string | null;
  connection_enabled: boolean;
  last_connected_at: string | null;
  broker_account_id: string;
  name: string;
  server: string;
  environment: AccountEnvironment;
  currency: string;
  leverage: number | null;
  balance: Decimal | null;
  equity: Decimal | null;
  margin: Decimal | null;
  free_margin: Decimal | null;
  trading_enabled: boolean;
  risk_profile: { id: string; name: string } | null;
  active_strategies: string[];
  capabilities: Capabilities;
  synced_at: string | null;
  created_at: string | null;
}

export interface Connection {
  id: string;
  label: string;
  connector_type: ConnectorType;
  broker: string;
  expected_environment: AccountEnvironment;
  status: ConnectionStatus;
  status_detail: string | null;
  is_enabled: boolean;
  has_credentials: boolean;
  settings: Record<string, unknown>;
  last_connected_at: string | null;
  last_error_at: string | null;
  accounts: Account[];
}

export interface ConnectorField {
  name: string;
  label: string;
  kind: "text" | "password" | "number" | "select" | "boolean" | "url";
  secret?: boolean;
  help?: string;
  default?: string;
  options?: string[];
  required?: boolean;
}

export interface Connector {
  id: ConnectorType;
  name: string;
  tagline: string;
  description: string;
  environments: AccountEnvironment[];
  auth_methods: ("none" | "pat" | "oauth" | "credentials")[];
  fields: ConnectorField[];
  status: "available" | "needs_setup";
  status_detail: string | null;
}

export interface ConnectionTestResult {
  account: {
    account_id: string;
    name: string;
    server: string;
    currency: string;
    environment: AccountEnvironment;
    balance: Decimal | null;
    equity: Decimal | null;
    leverage: number | null;
    trade_allowed: boolean;
  };
  symbol_count: number;
  categories: Record<string, number>;
  capabilities: Capabilities;
  normalized_settings: Record<string, unknown>;
  warnings: string[];
}

export interface DerivAccount {
  account_id: string;
  account_type: "demo" | "real";
  currency: string;
  balance: Decimal;
  status: string;
}

export interface RiskCheck {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface Trade {
  id: string;
  account: { id: string; label: string; environment: AccountEnvironment; currency: string } | null;
  strategy: string | null;
  strategy_version: number | null;
  source: "STRATEGY" | "MANUAL" | "EXTERNAL";
  symbol: string;
  side: Side;
  status: "OPEN" | "CLOSED";
  volume: Decimal;
  entry_price: Decimal;
  entry_time: string | null;
  stop_loss: Decimal | null;
  take_profit: Decimal | null;
  initial_stop_loss: Decimal | null;
  risk_amount: Decimal | null;
  exit_price: Decimal | null;
  exit_time: string | null;
  exit_reason: string | null;
  gross_pnl: Decimal | null;
  commission: Decimal | null;
  swap: Decimal | null;
  net_pnl: Decimal | null;
  unrealized_pnl: Decimal | null;
  r_multiple: Decimal | null;
  slippage_pips: Decimal | null;
  session: string | null;
  is_simulated: boolean;
}

/** Raw trade rows (Overview) use the database shape. */
export interface TradeRow {
  id: string;
  symbol: string;
  side: Side;
  volume: Decimal;
  entry_price: Decimal;
  entry_time: string;
  exit_price: Decimal | null;
  exit_time: string | null;
  exit_reason: string | null;
  net_pnl: Decimal | null;
  unrealized_pnl: Decimal | null;
  stop_loss: Decimal | null;
  take_profit: Decimal | null;
  is_simulated: boolean;
}

export interface Order {
  id: string;
  client_order_id: string;
  account: { id: string; label: string; environment: AccountEnvironment } | null;
  purpose: "ENTRY" | "EXIT";
  symbol: string;
  side: Side;
  order_type: string;
  volume: Decimal;
  filled_volume: Decimal;
  requested_price: Decimal | null;
  fill_price: Decimal | null;
  stop_loss: Decimal | null;
  take_profit: Decimal | null;
  status: string;
  broker_order_id: string | null;
  broker_message: string | null;
  is_simulated: boolean;
  created_at: string;
  submitted_at: string | null;
  filled_at: string | null;
}

export interface Signal {
  id: string;
  source: "STRATEGY" | "MANUAL";
  account: { id: string; label: string; environment: AccountEnvironment } | null;
  version: { id: string; version: number; strategy: { id: string; name: string } | null } | null;
  symbol: string;
  side: Side;
  bar_time: string;
  entry_price: Decimal;
  stop_loss: Decimal;
  take_profit: Decimal | null;
  reasons: string[];
  status: "NEW" | "APPROVED" | "REJECTED" | "SKIPPED" | "EXECUTED" | "FAILED";
  risk_checks: RiskCheck[];
  rejection_reason: string | null;
  volume: Decimal | null;
  risk_amount: Decimal | null;
  created_at: string;
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

export interface Paginated<T> {
  data: T[];
  current_page: number;
  last_page: number;
  per_page: number;
  total: number;
}

export interface Overview {
  account: {
    id: string;
    label: string;
    broker: string;
    connector_type: ConnectorType;
    environment: AccountEnvironment;
    currency: string;
    connection_status: ConnectionStatus;
    connection_detail: string | null;
    trading_enabled: boolean;
    synced_at: string | null;
    risk_profile: string | null;
  } | null;
  figures?: {
    balance: number | null;
    equity: number | null;
    today_pnl: number;
    total_pnl: number;
    open_pnl: number;
    open_positions: number;
    drawdown_pct: number | null;
    max_drawdown_pct: number | null;
    risk_used_pct: number | null;
    max_total_risk_pct: number | null;
    daily_loss_pct: number | null;
    max_daily_loss_pct: number | null;
    active_strategies: number;
  };
  robot: TradingStatus;
  equity_curve?: { t: string; balance: number; equity: number }[];
  positions?: TradeRow[];
  recent_trades?: TradeRow[];
  strategies?: {
    id: string;
    strategy: string | null;
    version: number | null;
    symbol: string;
    status: "ENABLED" | "PAUSED";
    status_reason: string | null;
    last_bar_evaluated: string | null;
    last_signal_at: string | null;
  }[];
  alerts?: { severity: string; message: string; at?: string }[];
}

export interface Instrument {
  name: string;
  canonical: string;
  description: string;
  category: string;
  digits: number;
  trade_allowed: boolean;
  market_open: boolean | null;
}

export interface Quote {
  symbol: string;
  bid: Decimal;
  ask: Decimal;
  spread: Decimal;
  time: string;
}

export interface SymbolSpec {
  name: string;
  canonical: string;
  description: string;
  category: string;
  base_currency: string;
  quote_currency: string;
  digits: number;
  point: Decimal;
  pip_size: Decimal;
  contract_size: Decimal;
  volume_min: Decimal;
  volume_max: Decimal;
  volume_step: Decimal;
  trade_allowed: boolean;
  market_open: boolean | null;
}

export interface Candle {
  time: string;
  open: Decimal;
  high: Decimal;
  low: Decimal;
  close: Decimal;
  volume: number;
}

export interface TicketPreview {
  approved: boolean;
  checks: RiskCheck[];
  entry_price: Decimal | null;
  spread: Decimal | null;
  volume: Decimal | null;
  suggested_volume: Decimal | null;
  risk_amount: Decimal | null;
  reward_risk: Decimal | null;
  reward_amount: Decimal | null;
  currency: string;
  symbol: SymbolSpec | null;
  rejection_reason: string | null;
  notes: string[];
}

export interface TicketResult {
  signal_id: string;
  status: Signal["status"];
  rejection_reason: string | null;
  risk_checks: RiskCheck[];
  volume: Decimal | null;
  risk_amount: Decimal | null;
  order: { id: string; status: string; fill_price: Decimal | null; broker_message: string | null; is_simulated: boolean } | null;
  trade_id: string | null;
}

export interface StrategyVersion {
  id: string;
  strategy_id: string;
  version: number;
  code_version: string;
  parameters: Record<string, unknown>;
  notes: string;
  created_at: string;
}

export interface Assignment {
  id: string;
  strategy_id: string;
  strategy_version_id: string;
  version: number | null;
  account: { id: string; label: string; environment: AccountEnvironment } | null;
  symbol: string;
  status: "ENABLED" | "PAUSED";
  status_reason: string | null;
  last_bar_evaluated: string | null;
  last_signal_at: string | null;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  $ref?: string;
  allOf?: { $ref: string }[];
}

export interface Strategy {
  id: string;
  key: string;
  name: string;
  description: string;
  code_version: string | null;
  parameter_schema: { properties: Record<string, JsonSchemaProperty>; $defs?: Record<string, { enum?: string[] }> } | null;
  versions: StrategyVersion[];
  assignments: Assignment[];
  live_trades: number;
  live_net_pnl: number;
  last_backtest: { id: string; status: string; metrics: Metrics | null } | null;
}

export interface Evaluation {
  id: number;
  bar_time: string;
  outcome: "SIGNAL" | "NO_SETUP" | "INSUFFICIENT_DATA";
  summary: string;
  checks: { name: string; passed: boolean; detail: string }[];
}

export interface Metrics {
  starting_balance: number | null;
  ending_balance: number | null;
  net_pnl: number | null;
  return_pct: number | null;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  expectancy: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_rr: number | null;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  total_costs: number | null;
  avg_holding_hours: number | null;
  equity_curve: { t: string; equity: number }[];
  drawdown_curve: { t: string; dd: number }[];
  monthly: { month: string; net_pnl: number; trades: number; return_pct: number | null }[];
  by_symbol: GroupStat[];
  by_session: GroupStat[];
  by_side: GroupStat[];
  by_strategy: GroupStat[];
}

export interface GroupStat {
  key: string;
  trades: number;
  wins: number;
  win_rate: number | null;
  net_pnl: number | null;
  profit_factor: number | null;
}

export interface Performance extends Partial<Metrics> {
  has_data: boolean;
  simulated: boolean;
  scope: { type: "account" | "environment"; label: string | null; environment: AccountEnvironment | null };
  unrealized_pnl?: number;
  open_positions?: number;
  balance_history?: { t: string; balance: number; equity: number }[];
  daily?: { period: string; net_pnl: number; trades: number }[];
  weekly?: { period: string; net_pnl: number; trades: number }[];
  execution?: {
    orders: number;
    fill_rate: number | null;
    avg_slippage_pips: number | null;
    worst_slippage_pips: number | null;
    avg_fill_seconds: number | null;
    unresolved_orders: number;
    signals_by_status: Record<string, number>;
    top_rejections: { reason: string; count: number }[];
  };
}

export interface Dataset {
  id: string;
  symbol: string;
  timeframe: string;
  source: "broker" | "csv" | "synthetic";
  description: string;
  first_bar: string | null;
  last_bar: string | null;
  bar_count: number;
  gap_count: number;
}

export interface Backtest {
  id: string;
  name: string;
  kind: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  strategy_key: string;
  symbol: string;
  timeframe: string;
  data_source: string;
  start: string;
  end: string;
  initial_capital: Decimal;
  progress: number;
  metrics: Metrics | null;
  report: { warnings?: string[]; [key: string]: unknown } | null;
  costs?: Record<string, string | null>;
  parameters?: Record<string, unknown>;
  risk_settings?: Record<string, unknown>;
  config?: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  children?: Backtest[];
}

export interface BacktestTrade {
  id: number;
  side: Side;
  signal_time: string;
  entry_time: string;
  entry_price: Decimal;
  exit_time: string;
  exit_price: Decimal;
  exit_reason: string;
  volume: Decimal;
  stop_loss: Decimal;
  take_profit: Decimal | null;
  risk_amount: Decimal;
  costs: Decimal;
  net_pnl: Decimal;
  r_multiple: Decimal;
  session: string;
  reasons: string[];
}

export interface RiskProfile {
  id: string;
  name: string;
  risk_per_trade_pct: Decimal;
  max_position_lots: Decimal | null;
  max_open_positions: number | null;
  max_positions_per_symbol: number | null;
  max_symbol_exposure_lots: Decimal | null;
  max_total_exposure_lots: Decimal | null;
  max_total_risk_pct: Decimal | null;
  max_daily_loss_pct: Decimal | null;
  max_weekly_loss_pct: Decimal | null;
  max_drawdown_pct: Decimal | null;
  max_trades_per_day: number | null;
  max_spread_pips: Decimal | null;
  max_slippage_pips: Decimal | null;
  min_stop_pips: Decimal | null;
  max_stop_pips: Decimal | null;
  min_reward_risk: Decimal | null;
  allowed_sessions: string[];
  trading_hours_start: string | null;
  trading_hours_end: string | null;
  cooldown_after_losses: number | null;
  cooldown_minutes: number | null;
  max_data_age_seconds: number;
  accounts_count?: number;
}

export interface RiskUsage {
  account: { id: string; label: string; environment: AccountEnvironment; currency: string };
  profile: RiskProfile | null;
  usage: { key: string; label: string; used: number | null; limit: number | null; unit: string }[];
}

export interface AppNotification {
  id: number;
  type: string;
  severity: Severity;
  title: string;
  message: string;
  account_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
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
  details: Record<string, unknown>;
}

export interface SystemStatus {
  app: string;
  environment: string;
  database: string;
  trading: TradingStatus;
  engine: { status: string; detail?: string; version?: string; engine_leader?: boolean; deriv_app_id_configured?: boolean };
  live_trading_enabled: boolean;
  broker_vault_configured: boolean;
  deriv_app_id_configured: boolean;
  mfa_required: boolean;
  queue_connection: string;
}
