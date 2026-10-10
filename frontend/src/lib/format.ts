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
    "trading.kill_switch.engaged": "Stopped trading",
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
  // Forex pairs (EURUSD): 5 decimals, JPY pairs 3; other markets (e.g. R_75 indices) 4.
  const forex = symbol ? /^[A-Z]{6}$/.test(symbol) : false;
  const digits = symbol ? (forex ? (symbol.includes("JPY") ? 3 : 5) : 4) : Math.min(5, (String(value).split(".")[1] ?? "").length || 2);
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

/** Valid ISO 4217 code? (Intl throws a RangeError otherwise.) */
function currencyFormatter(currency: string | null | undefined, signDisplay: "auto" | "never" = "auto"): Intl.NumberFormat | null {
  if (!currency || !/^[A-Z]{3}$/.test(currency)) return null;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, currencyDisplay: "narrowSymbol", minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay });
  } catch {
    return null;
  }
}

/** "$1,234.56" in the account currency (falls back to "1,234.56 XYZ" for unknown codes). */
export function formatCurrency(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const f = currencyFormatter(currency);
  return f ? f.format(n) : formatMoney(n, currency ?? undefined);
}

/** Signed money in the account currency: "+$12.50", "−$3.20" (true minus sign), "$0.00". */
export function formatSignedCurrency(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const f = currencyFormatter(currency, "never");
  const abs = f ? f.format(Math.abs(n)) : formatMoney(Math.abs(n), currency ?? undefined);
  const rounded = Math.round(n * 100);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return `${sign}${abs}`;
}

/** Compact duration: 45 → "45s", 310 → "5m 10s", 7500 → "2h 5m", 280000 → "3d 5h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return EMPTY;
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 ? `${m}m ${s % 60}s` : `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d}d ${h % 24}h` : `${d}d`;
}

/** Time left until `iso`: "4:59", "1:02:03"; "0:00" once passed; null without a time. */
export function formatCountdown(iso: string | null | undefined, now: number = Date.now()): string | null {
  if (!iso) return null;
  const end = new Date(iso).getTime();
  if (Number.isNaN(end)) return null;
  const left = Math.max(0, Math.floor((end - now) / 1000));
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  const s = left % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}
