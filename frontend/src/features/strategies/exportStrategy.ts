/**
 * Download a rule-based strategy as a 2kPilot strategy file
 * (GET /api/strategies/{id}/export → `<slug>.tradepilot.json`).
 */
import { ApiError } from "@/lib/api";

/** "My EMA cross!" → "my-ema-cross" (falls back to "strategy"). */
export function strategySlug(name: string): string {
  const slug = name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
    .replace(/-+$/g, "");
  return slug || "strategy";
}

export function exportFileName(name: string): string {
  return `${strategySlug(name)}.tradepilot.json`;
}

/** Fetches the export and saves it as a file. Throws ApiError on failure. */
export async function exportStrategy(strategy: { id: string; name: string }): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/strategies/${encodeURIComponent(strategy.id)}/export`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the 2kPilot server. Check that it is running (make dev).");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { message?: string; code?: string } | null;
    throw new ApiError(response.status, payload?.code ?? "http_error", payload?.message ?? `Export failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob.type ? blob : new Blob([blob], { type: "application/json" }));
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = exportFileName(strategy.name);
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Give the browser a moment to start the download before revoking.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
