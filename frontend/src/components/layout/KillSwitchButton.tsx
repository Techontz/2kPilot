"use client";

import { OctagonX, Play } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ApiError } from "@/lib/api";
import { resumeTrading, stopAllTrading } from "@/lib/trading";

interface KillSwitchButtonProps {
  reason?: string;
  size?: "sm" | "md";
}

/**
 * STOP is one click — the safe action must never be slowed down.
 * RESUME is deliberate — it requires confirmation.
 */
export function KillSwitchButton({ reason, size = "md" }: KillSwitchButtonProps) {
  const { isOwner } = useSession();
  const { status, applyTradingStatus } = useSystemStatus();
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!status || !isOwner) return null;
  const engaged = status.trading.kill_switch_engaged;

  const run = async (action: () => Promise<Parameters<typeof applyTradingStatus>[0]>) => {
    setBusy(true);
    setError(null);
    try {
      applyTradingStatus(await action());
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  if (!engaged) {
    return (
      <>
        <Button
          variant="danger"
          size={size}
          disabled={busy}
          aria-label="STOP ALL TRADING"
          onClick={() => run(() => stopAllTrading(reason))}
        >
          <OctagonX aria-hidden className="size-4" />
          {busy ? "Stopping…" : (
            <>
              <span className="sm:hidden">STOP</span>
              <span className="hidden sm:inline">STOP ALL TRADING</span>
            </>
          )}
        </Button>
        {error && (
          <span role="alert" className="text-xs text-negative">
            {error}
          </span>
        )}
      </>
    );
  }

  return (
    <>
      <Button variant="secondary" size={size} aria-label="Resume trading" onClick={() => setConfirmOpen(true)}>
        <Play aria-hidden className="size-4" />
        <span className="sm:hidden">Resume</span>
        <span className="hidden sm:inline">Resume trading</span>
      </Button>
      <ConfirmDialog
        open={confirmOpen}
        title="Resume trading?"
        confirmLabel="Resume trading"
        busy={busy}
        error={error}
        onConfirm={() => run(resumeTrading)}
        onCancel={() => {
          setConfirmOpen(false);
          setError(null);
        }}
      >
        <p>
          This releases the kill switch. Enabled strategies will be allowed to place new orders in{" "}
          <strong className="text-fg">{status.trading.trading_mode}</strong> mode, subject to every risk rule.
        </p>
        <p>You can stop again at any time with STOP ALL TRADING.</p>
      </ConfirmDialog>
    </>
  );
}
