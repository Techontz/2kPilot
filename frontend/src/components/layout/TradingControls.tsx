"use client";

import { OctagonX, Play } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Field, TextInput } from "@/components/ui/Fields";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAction } from "@/lib/hooks";
import { deriveRobotStatus, MODE_INFO } from "@/lib/status";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";

const DOT = { positive: "bg-positive", warning: "bg-warning", negative: "bg-negative", neutral: "bg-fg-subtle", live: "bg-live", info: "bg-info" };

/** "Is my robot running?" */
export function RobotStatusPill() {
  const { status } = useAppData();
  if (!status) return null;
  const robot = deriveRobotStatus(status);
  return (
    <div className="hidden items-center gap-2 rounded-lg border border-line px-3 py-1.5 lg:flex" title={robot.detail}>
      <span className={cn("size-2 rounded-full", DOT[robot.tone], robot.running && "animate-pulse")} aria-hidden />
      <span className="text-sm text-fg">{robot.label}</span>
      <span className="text-xs text-fg-subtle">· {MODE_INFO[status.trading_mode].label} mode</span>
    </div>
  );
}

/**
 * The permanent STOP TRADING control. Stopping blocks every new trade
 * (automated and manual) and NEVER closes positions — that is a separate
 * action on the Risk page.
 */
export function StopTradingButton() {
  const { status, reloadStatus } = useAppData();
  const { isOwner } = useSession();
  const [dialog, setDialog] = useState<"stop" | "resume" | null>(null);
  const [reason, setReason] = useState("");
  const action = useAction();
  if (!status) return null;
  const stopped = status.kill_switch_engaged;

  const confirm = async () => {
    const ok = await action.run(() =>
      stopped
        ? api("/trading/resume", { method: "POST", body: { confirm: true } })
        : api("/trading/stop", { method: "POST", body: { reason: reason || "Stopped from the dashboard" } }),
    );
    if (ok !== null) {
      setDialog(null);
      setReason("");
      await reloadStatus();
    }
  };

  return (
    <>
      {stopped ? (
        <Button variant="secondary" disabled={!isOwner} onClick={() => setDialog("resume")} title="Trading is stopped" className="shrink-0 px-3 sm:px-4">
          <Play className="size-4 text-positive" aria-hidden />
          <span className="hidden sm:inline">Resume trading</span>
          <span className="sm:hidden">Resume</span>
        </Button>
      ) : (
        <Button variant="danger" disabled={!isOwner} onClick={() => setDialog("stop")} className="shrink-0 px-3 font-semibold tracking-wide sm:px-4" aria-label="Stop trading">
          <OctagonX className="size-4" aria-hidden />
          <span className="hidden sm:inline">STOP TRADING</span>
          <span className="sm:hidden">STOP</span>
        </Button>
      )}
      <ConfirmDialog
        open={dialog === "stop"}
        title="Stop all trading?"
        confirmLabel="Stop trading"
        confirmVariant="danger"
        busy={action.busy}
        error={action.error}
        onConfirm={confirm}
        onCancel={() => setDialog(null)}
      >
        <p>No new trades will be opened — by any strategy or by hand — until you resume.</p>
        <p><strong className="text-fg">Open positions stay open.</strong> To close them, use “Close positions” on the Risk page.</p>
        <Field label="Reason (optional)">
          <TextInput value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. news event" maxLength={300} />
        </Field>
      </ConfirmDialog>
      <ConfirmDialog
        open={dialog === "resume"}
        title="Resume trading?"
        confirmLabel="Resume trading"
        busy={action.busy}
        error={action.error}
        onConfirm={confirm}
        onCancel={() => setDialog(null)}
      >
        <p>Enabled strategies may open trades again in <strong className="text-fg">{MODE_INFO[status.trading_mode].label}</strong> mode. Every order still passes the risk engine.</p>
        {status.engine_state === "offline" && <p className="text-warning">The trading engine is offline, so nothing will trade until it is running.</p>}
      </ConfirmDialog>
    </>
  );
}
