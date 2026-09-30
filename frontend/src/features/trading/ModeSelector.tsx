"use client";

import { Lock } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { inputClass } from "@/components/ui/inputClass";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MODE_INFO } from "@/lib/status";
import { LIVE_CONFIRMATION_PHRASE, setTradingMode } from "@/lib/trading";
import type { TradingMode, TradingStatus } from "@/lib/types";

const MODES: TradingMode[] = ["BACKTEST", "DEMO", "LIVE"];

export function ModeSelector({ trading }: { trading: TradingStatus }) {
  const { isOwner } = useSession();
  const { applyTradingStatus } = useSystemStatus();
  const [pending, setPending] = useState<TradingMode | null>(null);
  const [password, setPassword] = useState("");
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canChange = isOwner && trading.kill_switch_engaged;

  const close = () => {
    setPending(null);
    setPassword("");
    setPhrase("");
    setError(null);
  };

  const confirm = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const next = await setTradingMode(pending, pending === "LIVE" ? { password, phrase } : undefined);
      applyTradingStatus(next);
      close();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Mode change failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Operating mode"
        description={
          trading.kill_switch_engaged
            ? "Choose where orders are allowed to go."
            : "Stop all trading before changing mode."
        }
      />
      <CardBody>
        <div role="radiogroup" aria-label="Operating mode" className="grid gap-3 md:grid-cols-3">
          {MODES.map((mode) => {
            const info = MODE_INFO[mode];
            const selected = trading.trading_mode === mode;
            const locked = mode === "LIVE" && trading.live_trading_locked;
            return (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={!canChange || selected || locked}
                onClick={() => setPending(mode)}
                className={cn(
                  "rounded-lg border p-4 text-left transition-colors disabled:cursor-not-allowed",
                  selected
                    ? mode === "LIVE"
                      ? "border-live bg-live-soft"
                      : "border-accent bg-surface-raised"
                    : "border-line hover:enabled:bg-surface-raised",
                  locked && "opacity-60",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className={cn("text-sm font-semibold", mode === "LIVE" ? "text-live" : "text-fg")}>
                    {info.label}
                  </span>
                  {selected && <span className="text-xs text-accent">Current</span>}
                  {locked && (
                    <span className="flex items-center gap-1 text-xs text-fg-subtle">
                      <Lock aria-hidden className="size-3" /> Locked
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-fg-muted">{info.explanation}</p>
              </button>
            );
          })}
        </div>
        {trading.live_trading_locked && (
          <p className="mt-4 text-xs text-fg-subtle">
            LIVE is disabled on this server (LIVE_TRADING_ENABLED=false). It stays locked until the
            live-readiness review is complete — see each account&apos;s readiness checklist on the Brokers page.
          </p>
        )}
      </CardBody>

      <ConfirmDialog
        open={pending !== null}
        title={pending === "LIVE" ? "Switch to LIVE — real money" : `Switch to ${pending ? MODE_INFO[pending].label : ""}?`}
        confirmLabel={pending === "LIVE" ? "Enable LIVE mode" : "Switch mode"}
        confirmVariant={pending === "LIVE" ? "danger" : "primary"}
        busy={busy}
        error={error}
        confirmDisabled={pending === "LIVE" && (password.length === 0 || phrase !== LIVE_CONFIRMATION_PHRASE)}
        onConfirm={() => void confirm()}
        onCancel={close}
      >
        {pending && <p>{MODE_INFO[pending].explanation}</p>}
        <p>Trading stays stopped after the switch. You must resume it separately.</p>
        {pending === "LIVE" && (
          <>
            <label className="block text-xs text-fg-muted">
              Your password
              <input
                className={inputClass}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label className="block text-xs text-fg-muted">
              Type <span className="num text-fg">{LIVE_CONFIRMATION_PHRASE}</span> to confirm
              <input className={inputClass} value={phrase} onChange={(e) => setPhrase(e.target.value)} />
            </label>
          </>
        )}
      </ConfirmDialog>
    </Card>
  );
}
