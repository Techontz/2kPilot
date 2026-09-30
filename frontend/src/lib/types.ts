// Mirrors the backend response schemas (backend/src/fxrobot/schemas).

export type TradingMode = "BACKTEST" | "DEMO" | "LIVE";
export type UserRole = "owner" | "viewer";
export type EngineState = "offline";

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
}

export type ConnectorStatus = "available" | "unavailable" | "planned";

export interface Connector {
  id: string;
  name: string;
  status: ConnectorStatus;
  status_detail: string;
  fields: { name: string; label: string; secret: boolean; help: string }[];
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
