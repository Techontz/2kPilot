"use client";

import { Siren } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Toggle } from "@/components/ui/Fields";
import { apiRequest } from "@/lib/api";
import type { TradingStatus } from "@/lib/types";
import { useAction } from "@/lib/useAction";

export function EmergencyStop() {
  const { isOwner } = useSession();
  const { applyTradingStatus } = useSystemStatus();
  const [open, setOpen] = useState(false);
  const [closeAll, setCloseAll] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const action = useAction();
  if (!isOwner) return null;
  const run = async () => {
    const res = await action.run(() =>
      apiRequest<{ result: { closed: number; failed: string[] }; status: TradingStatus }>("/trading/emergency-stop", {
        method: "POST",
        body: { reason: "Emergency stop from Risk Management", close_positions: closeAll },
      }),
    );
    if (res) {
      applyTradingStatus(res.status);
      setResult(closeAll ? `Stopped. Closed ${res.result.closed} position(s)${res.result.failed.length ? `; ${res.result.failed.length} failed` : ""}.` : "Stopped. Open positions were left in place.");
      setOpen(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Emergency stop" description="Stops all trading. Closing every position is a separate, optional choice." />
      <CardBody className="space-y-3">
        <Button variant="danger-outline" onClick={() => setOpen(true)}><Siren aria-hidden className="size-4" />Emergency stop…</Button>
        {result && <p className="text-sm text-fg-muted">{result}</p>}
      </CardBody>
      <ConfirmDialog open={open} title="Emergency stop" confirmLabel={closeAll ? "Stop and close everything" : "Stop trading"} confirmVariant="danger"
        busy={action.busy} error={action.error} onCancel={() => setOpen(false)} onConfirm={() => void run()}>
        <p>This engages STOP ALL TRADING immediately.</p>
        <Toggle checked={closeAll} onChange={setCloseAll} label="Also close ALL open positions at market"
          description="Market orders close every position now, locking in current profits and losses. Leave off to keep them protected by their stop losses." />
      </ConfirmDialog>
    </Card>
  );
}
