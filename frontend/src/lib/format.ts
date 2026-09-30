export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDateTime(iso);
}

/** "trading.kill_switch.engaged" → "Trading · kill switch engaged" */
export function describeAuditAction(action: string): string {
  const known: Record<string, string> = {
    "auth.login.succeeded": "Signed in",
    "auth.login.failed": "Failed sign-in attempt",
    "auth.login.rate_limited": "Sign-in blocked (too many attempts)",
    "auth.logout": "Signed out",
    "user.created": "User created",
    "trading.kill_switch.engaged": "Stopped all trading",
    "trading.kill_switch.released": "Resumed trading",
    "trading.mode.changed": "Changed operating mode",
    "trading.mode.live_enabled": "Enabled LIVE mode",
    "trading.mode.change_denied": "Mode change refused",
    "trading.emergency_stop": "Emergency stop",
    "broker.added": "Broker added",
    "broker.removed": "Broker removed",
    "account.updated": "Account settings changed",
    "account.trading_enable_denied": "Enable trading refused",
    "strategy.version_created": "Strategy version created",
    "strategy.assigned": "Strategy assigned",
    "strategy.enabled": "Strategy enabled",
    "strategy.paused": "Strategy paused",
    "strategy.modified": "Strategy modified",
    "strategy.unassigned": "Strategy removed from account",
    "risk.profile_created": "Risk profile created",
    "risk.settings_changed": "Risk settings changed",
    "risk.profile_deleted": "Risk profile deleted",
    "position.closed_manually": "Position closed manually",
    "position.modified_manually": "Position modified manually",
    "backtest.started": "Backtest started",
    "backtest.deleted": "Backtest deleted",
    "data.imported": "Data imported",
    "data.synthetic_generated": "Synthetic data generated",
    "data.downloaded": "Data downloaded",
    "data.deleted": "Dataset deleted",
  };
  if (known[action]) return known[action];
  const [domain = "", ...rest] = action.split(".");
  return `${domain.charAt(0).toUpperCase()}${domain.slice(1)} · ${rest.join(" ").replaceAll("_", " ")}`;
}

const EMPTY = "—";

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** 12,345.67 USD-style money (no symbol; currency shown separately). */
export function formatMoney(value: string | number | null | undefined, currency?: string): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const text = n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${text} ${currency}` : text;
}

/** Signed money, e.g. "+12.50" / "−3.20" (true minus sign). */
export function formatPnl(value: string | number | null | undefined, currency?: string): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const abs = Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${abs}${currency ? ` ${currency}` : ""}`;
}

export function formatPct(value: string | number | null | undefined, digits = 2, signed = false): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const sign = signed && n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(digits)}%`;
}

export function formatNumber(value: string | number | null | undefined, digits = 2): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Price with the symbol's precision (JPY pairs 3, most FX 5). */
export function formatPrice(value: string | number | null | undefined, symbol?: string): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const digits = symbol ? (symbol.includes("JPY") ? 3 : 5) : Math.min(5, (String(value).split(".")[1] ?? "").length || 2);
  return n.toFixed(digits);
}

export function pnlTone(value: string | number | null | undefined): "positive" | "negative" | "neutral" {
  const n = toNumber(value);
  if (n === null || n === 0) return "neutral";
  return n > 0 ? "positive" : "negative";
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? EMPTY : date.toLocaleString(undefined, {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? EMPTY : date.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
  });
}

export function humanize(text: string): string {
  const lower = text.replaceAll("_", " ").toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
