/**
 * Shapes returned by the Laravel API (backend/app/Http/Controllers/Api).
 * Money, prices and volumes arrive as DECIMAL strings — never floats — and
 * are only formatted for display (lib/format.ts).
 */

export type Decimal = string;
export type AccountEnvironment = "PAPER" | "DEMO" | "LIVE" | "UNKNOWN";
export type ConnectionStatus = "CONNECTED" | "DISCONNECTED" | "RECONNECTING" | "ERROR";
export type ConnectorType = "paper" | "deriv";
export type TradingMode = "DEMO" | "LIVE";
export type EngineState = "offline" | "running" | "degraded";
export type Side = "BUY" | "SELL";
export type Severity = "info" | "success" | "warning" | "critical";

export interface User {
  id: string;
  name: string;
  email: string;
  role: "user" | "admin";
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
  live_authorized_at: string | null;
  platform_halted: boolean;
  platform_halt_reason: string | null;
  engine_state: EngineState;
  engine_detail: string;
  engine_heartbeat_at: string | null;
  new_orders_permitted: boolean;
  /** Typed phrase required to authorise LIVE (PUT /api/trading/mode). */
  live_confirmation_phrase?: string;
  /** The one LIVE account the authorisation covers. */
  live_authorized_account_id?: string | null;
  /** Why real-money authorisation was last taken away (profile edited, MFA off, …); cleared by a new authorisation. */
  live_revoked_reason?: string | null;
  live_revoked_at?: string | null;
  /**
   * Display-only engine health (additive; older servers omit them). Kept apart
   * from `new_orders_permitted`, which stays heartbeat-based on the server.
   */
  engine_service?: EngineService | null;
  engine_supervisor?: EngineSupervisor;
  engine_summary?: EngineSummary;
}

/** Does the Python engine's HTTP API answer its signed health check? */
export interface EngineService {
  status: "online" | "error" | "unreachable";
  reachable: boolean;
  /** The engine's ENGINE_ENABLED (automated-trading supervisor switched on), when known. */
  supervisor_enabled: boolean | null;
  version: string | null;
  checked_at: string;
  detail: string | null;
}

/** The automated-trading supervisor: switched on, and is its heartbeat fresh? */
export interface EngineSupervisor {
  state: "running" | "degraded" | "stale" | "not_started" | "disabled" | "unknown";
  heartbeat_at: string | null;
  detail: string;
}

export type EngineSummaryCode =
  | "running" | "running_degraded" | "trading_disabled" | "supervisor_not_started" | "supervisor_stale" | "engine_error" | "engine_offline";

/** One dashboard line combining service + supervisor. */
export interface EngineSummary {
  code: EngineSummaryCode;
  tone: "ok" | "info" | "warning" | "error";
  label: string;
  message: string;
  trading_active: boolean;
}

/** Body of PUT /api/trading/mode. LIVE also needs the user's LIVE account (with a risk profile) to authorise. */
export interface TradingModeRequest {
  mode: TradingMode;
  password?: string | null;
  confirmation_phrase?: string | null;
  account_id?: string;
  mfa_code?: string | null;
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
  // Contract trades (Rise/Fall, Multipliers); null for Spot.
  contract_family?: ContractFamily | null;
  contract_type?: string | null;
  broker_contract_id?: string | null;
  stake?: Decimal | null;
  payout?: Decimal | null;
  multiplier?: number | null;
  duration?: number | null;
  duration_unit?: DurationUnit | null;
  expires_at?: string | null;
  entry_spot?: Decimal | null;
  exit_spot?: Decimal | null;
  fees?: Decimal | null;
  outcome?: TradeOutcome | null;
  longcode?: string | null;
  duration_seconds?: number | null;
}

export type TradeOutcome = "OPEN" | "WON" | "LOST" | "SOLD" | "CANCELLED";

/** Trade rows on Home use the same shape as History. */
export type TradeRow = Trade;

// ── Contracts ───────────────────────────────────────────────────────────

export type ContractFamily = "RISE_FALL" | "MULTIPLIER" | "SPOT";
export type DurationUnit = "t" | "s" | "m" | "h" | "d";

/** How a BUY/SELL is traded (canonical form; fields that don't apply are null). */
export interface ContractSpec {
  contract_family: ContractFamily;
  duration: number | null;
  duration_unit: DurationUnit | null;
  allow_equals: boolean;
  stake: Decimal | null;
  multiplier: number | null;
  take_profit_amount: Decimal | null;
  stop_loss_amount: Decimal | null;
}

/** GET /api/markets/contracts — what a symbol offers on an account. */
export interface ContractOffer {
  account: { id: string; label: string; environment: AccountEnvironment };
  provider: string;
  symbol: string;
  simulated: boolean;
  market_open: boolean | null;
  trading_suspended: boolean;
  families: {
    RISE_FALL: { available: boolean; contract_types: string[]; allow_equals: boolean; durations: { expiry_type: string | null; min: string; max: string }[] };
    MULTIPLIER: { available: boolean; contract_types: string[]; multipliers: number[] };
    SPOT: { available: boolean };
  };
  default_contract: ContractSpec;
  notes: string[];
  fetched_at?: string;
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

export interface Blocker {
  code: string;
  message: string;
}

export interface ActiveStrategy {
  assignment_id: string;
  strategy_id: string;
  strategy: string | null;
  version: number | null;
  symbol: string;
  contract: ContractSpec;
  contract_summary: string;
  status_reason: string | null;
  last_bar_evaluated: string | null;
  last_signal_at: string | null;
}

export interface SetupChecklist {
  has_broker: boolean;
  has_account: boolean;
  has_strategy: boolean;
  has_backtest: boolean;
  has_active_strategy: boolean;
  trading_started: boolean;
  mfa_enabled: boolean;
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
    risk_profile_id?: string | null;
    balance?: Decimal | null;
    equity?: Decimal | null;
    broker_account_id?: string;
    connection_id?: string;
    last_connected_at?: string | null;
  } | null;
  broker?: { name: string; connector_type: ConnectorType; connection_status: ConnectionStatus; connection_detail: string | null; last_connected_at: string | null } | null;
  active_strategies?: ActiveStrategy[];
  blockers?: Blocker[];
  daily_pnl?: { date: string; net_pnl: number; trades: number }[];
  balance_history?: { t: string; balance: number; equity: number }[];
  setup?: SetupChecklist;
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
  strategy_id?: string;
  version: number;
  code_version: string;
  parameters: Record<string, unknown>;
  rules_text?: string | null;
  notes: string;
  created_at: string;
}

export interface Assignment {
  id: string;
  strategy_id: string;
  strategy_version_id: string;
  version: number | null;
  account: { id: string; label: string; environment: AccountEnvironment; connector_type?: ConnectorType | null } | null;
  symbol: string;
  contract?: ContractSpec;
  status: "ENABLED" | "PAUSED";
  status_reason: string | null;
  last_bar_evaluated: string | null;
  last_signal_at: string | null;
}

/** Result of POST /api/strategies/{id}/activate. */
export interface ActivationResult extends Assignment {
  contract_check: { verified: boolean; detail?: string } | null;
  blockers: Blocker[];
  will_trade: boolean;
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

export type StrategySource = "template" | "builder" | "ai" | "import" | "copy" | "code" | (string & {});

export interface StrategyDetails {
  how_it_works?: string;
  struggles?: string;
  difficulty?: "beginner" | "intermediate" | "advanced" | (string & {});
  disclaimer?: string;
  educational?: boolean;
  suggested_symbols?: string[];
  suggested_timeframe?: Timeframe;
  suggested_contract?: Partial<ContractSpec> & { contract_family: ContractFamily };
  suggested_contract_note?: string;
  /** Paper accounts: the contract to start from when it differs (e.g. Spot). */
  suggested_contract_paper?: Partial<ContractSpec> & { contract_family: ContractFamily };
  /** Set by the engine for code strategies with limits; missing = any. */
  supported_contract_families?: ContractFamily[];
  supported_symbols?: string[];
}

/** The "qualifies for demo forward testing" gate of a split / walk-forward test. */
export interface ValidationGate {
  qualifies_for_demo_forward_testing: boolean;
  checks: { name: string; passed: boolean; detail: string }[];
  reasons: string[];
  note: string;
}

export interface PerformanceStats {
  trades: number;
  wins: number;
  win_rate: number | null;
  net_pnl: number;
  net_pnl_30d: number;
  last_trade_at: string | null;
}

export interface BacktestHeadline {
  id: string;
  name: string;
  symbol: string;
  timeframe: string;
  net_pnl: number | null;
  return_pct: number | null;
  win_rate: number | null;
  trades: number | null;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  contract_family: ContractFamily | null;
  run_at: string | null;
  kind?: string;
  data_source?: string;
  profit_factor?: number | null;
  expectancy?: number | null;
  avg_rr?: number | null;
  longest_losing_streak?: number | null;
  by_regime?: GroupStat[];
  validation?: ValidationGate | null;
}

export interface Strategy {
  id: string;
  key: string;
  slug?: string | null;
  name: string;
  description: string;
  summary?: string | null;
  details?: StrategyDetails | null;
  source?: StrategySource;
  built_in: boolean;
  editable?: boolean;
  archived?: boolean;
  copied_from_id?: string | null;
  code_version: string | null;
  parameter_schema: { properties: Record<string, JsonSchemaProperty>; $defs?: Record<string, { enum?: string[] }> } | null;
  latest_version?: StrategyVersion | null;
  rules_text?: string | null;
  versions: StrategyVersion[];
  assignments: Assignment[];
  performance?: { demo: PerformanceStats; live: PerformanceStats | null };
  backtest?: BacktestHeadline | null;
  /** The latest completed backtest per market (results by instrument). */
  backtests_by_symbol?: BacktestHeadline[];
  /** Markets / contract families the strategy supports; null = any. */
  contract_families?: ContractFamily[] | null;
  symbols?: string[] | null;
  /** An administrator's emergency stop on new entries (inherited from the built-in for copies). */
  entries_disabled?: { at: string | null; reason: string | null; inherited: boolean } | null;
  live_trades: number;
  live_net_pnl: number;
  last_backtest: { id: string; status: string; metrics: Metrics | null } | null;
}

/** Export / import file (GET /api/strategies/{id}/export, POST /api/strategies/import). */
export interface StrategyFile {
  format: "tradepilot.strategy";
  schema_version: 1;
  name: string;
  description?: string | null;
  rules: RuleSet;
}

/** POST /api/strategies/draft — never saved; reviewed in the builder. */
export interface StrategyDraft {
  rules: RuleSet | null;
  rules_text: string | null;
  explanation: string;
  warnings: string[];
  unsupported: string[];
  notes: string[];
  model: string | null;
}

// ── Rule sets (schema_version 1) ────────────────────────────────────────

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";
export type PriceField = "open" | "high" | "low" | "close";
export type OperatorKey = "crosses_above" | "crosses_below" | "gt" | "gte" | "lt" | "lte" | "between";

/** Exactly one of price / value / indicator. Stored versions may carry explicit nulls. */
export interface Operand {
  price?: PriceField | null;
  value?: number | null;
  indicator?: string | null;
  params?: Record<string, number | string> | null;
  output?: string | null;
}

export interface Condition {
  left: Operand;
  op: OperatorKey;
  right?: Operand | null;
  low?: Operand | null;
  high?: Operand | null;
  within_bars?: number | null;
}

export interface ConditionGroup {
  all?: Condition[] | null;
  any?: Condition[] | null;
}

export interface StopRule {
  type: "atr" | "pips";
  atr_period?: number;
  multiple?: number;
  pips?: number | null;
}

export interface TargetRule {
  type: "rr" | "atr" | "pips";
  ratio?: number;
  atr_period?: number;
  multiple?: number;
  pips?: number | null;
}

export interface RuleSet {
  schema_version: 1;
  timeframe: Timeframe;
  entry: { buy?: ConditionGroup | null; sell?: ConditionGroup | null };
  filters?: Condition[];
  exit?: {
    stop?: StopRule;
    target?: TargetRule | null;
    close_buy_when?: ConditionGroup | null;
    close_sell_when?: ConditionGroup | null;
  };
}

/** GET /api/strategies/catalog — drives the visual builder. */
export interface RulesCatalog {
  schema_version: number;
  timeframes: Timeframe[];
  price_fields: { key: PriceField; label: string }[];
  indicators: CatalogIndicator[];
  operators: CatalogOperator[];
  groups: { key: "all" | "any"; label: string }[];
  stop_types: { key: StopRule["type"]; label: string; fields: string[] }[];
  target_types: { key: TargetRule["type"]; label: string; fields: string[] }[];
  limits: { max_conditions: number; min_period: number; max_period: number; max_within_bars: number; max_constant: number };
  contract_notes: Partial<Record<ContractFamily, string>>;
  ai_drafting_available?: boolean;
}

export interface CatalogParam {
  key: string;
  label: string;
  type: "integer" | "number" | "source";
  default: number | string;
  description: string;
  min?: number | null;
  max?: number | null;
  options?: PriceField[];
}

export interface CatalogIndicator {
  key: string;
  label: string;
  short: string;
  description: string;
  params: CatalogParam[];
  outputs: { key: string; label: string; scale: string; meaning: string }[];
  default_output: string;
  notes: string[];
}

export interface CatalogOperator {
  key: OperatorKey;
  label: string;
  description: string;
  operands: ("right" | "low" | "high")[];
  supports_within_bars?: boolean;
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
  /** Results by the market regime at entry (backtests). */
  by_regime?: GroupStat[];
  longest_losing_streak?: number;
  largest_win?: number | null;
  largest_loss?: number | null;
  breakeven?: number;
  // Contract backtests
  contract?: ContractSpec;
  payout_ratio?: number;
  payout_ratio_is_estimate?: boolean;
  commission_pct?: number;
  outcomes?: Partial<Record<"WON" | "LOST" | "SOLD", number>>;
  notes?: string[];
  signals?: number;
  rejections?: Record<string, number>;
  strategy_exits?: number;
}

export interface GroupStat {
  key: string;
  trades: number;
  wins: number;
  win_rate: number | null;
  net_pnl: number | null;
  profit_factor: number | null;
  expectancy?: number | null;
  expectancy_r?: number | null;
  avg_rr?: number | null;
  max_drawdown?: number | null;
  longest_losing_streak?: number;
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
  report: { warnings?: string[]; notes?: string[]; [key: string]: unknown } | null;
  costs?: Record<string, string | null>;
  parameters?: Record<string, unknown>;
  risk_settings?: Record<string, unknown>;
  config?: { contract?: ContractSpec | null; payout_ratio?: string | number | null; [key: string]: unknown } | null;
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
  contract_type?: string | null;
  stake?: Decimal | null;
  payout?: Decimal | null;
  outcome?: "WON" | "LOST" | "SOLD" | null;
  regime?: string | null;
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
  stake_amount: Decimal;
  max_stake_amount: Decimal | null;
  max_daily_loss_amount: Decimal | null;
  max_consecutive_losses: number | null;
  daily_profit_target_amount: Decimal | null;
  min_account_balance?: Decimal | null;
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
  /** Additive: the same engine health as in `trading`, at the top level. */
  engine_service?: EngineService | null;
  engine_supervisor?: EngineSupervisor;
  engine_summary?: EngineSummary;
}
