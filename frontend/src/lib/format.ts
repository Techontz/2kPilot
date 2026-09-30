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
  };
  if (known[action]) return known[action];
  const [domain = "", ...rest] = action.split(".");
  return `${domain.charAt(0).toUpperCase()}${domain.slice(1)} · ${rest.join(" ").replaceAll("_", " ")}`;
}
