import type { Account, TradingStatus } from "@/lib/types";

export function tradingStatus(overrides: Partial<TradingStatus> = {}): TradingStatus {
  return {
    trading_mode: "DEMO",
    kill_switch_engaged: true,
    kill_switch_reason: null,
    kill_switch_changed_at: null,
    live_trading_locked: true,
    engine_state: "offline",
    engine_detail: "No heartbeat",
    engine_heartbeat_at: null,
    new_orders_permitted: false,
    ...overrides,
  };
}

export function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "acc-1",
    label: "Paper practice",
    broker: "Paper Trading",
    connector_type: "paper",
    connection_id: "conn-1",
    connection_status: "CONNECTED",
    connection_detail: "Connected",
    connection_enabled: true,
    last_connected_at: null,
    broker_account_id: "PAPER-1234",
    name: "Paper account",
    server: "2kFX Paper (SYNTHETIC)",
    environment: "PAPER",
    currency: "USD",
    leverage: 100,
    balance: "10000.000000",
    equity: "10012.500000",
    margin: null,
    free_margin: null,
    trading_enabled: false,
    risk_profile: { id: "rp-1", name: "Conservative (default)" },
    active_strategies: [],
    capabilities: { volume_unit: "lots" },
    synced_at: null,
    created_at: null,
    ...overrides,
  };
}
