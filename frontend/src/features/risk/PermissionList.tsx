import { ModeBadge } from "@/components/layout/ModeBadge";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";
import type { TradingStatus } from "@/lib/types";

function Row({ label, value, detail }: { label: string; value: React.ReactNode; detail: string }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 py-3.5">
      <div>
        <p className="text-sm text-fg">{label}</p>
        <p className="mt-0.5 text-xs text-fg-subtle">{detail}</p>
      </div>
      <div className="shrink-0">{value}</div>
    </div>
  );
}

/** Every gate that must be open before a single order can be placed. */
export function PermissionList({ trading }: { trading: TradingStatus }) {
  return (
    <Card>
      <CardHeader title="Trading permissions" description="All must allow trading before any order is sent." />
      <div className="divide-y divide-line">
        <Row
          label="Kill switch"
          detail="Global STOP ALL TRADING control."
          value={
            trading.kill_switch_engaged ? <Badge tone="warning">Engaged</Badge> : <Badge tone="positive">Released</Badge>
          }
        />
        <Row label="Operating mode" detail="Which kind of account orders may reach." value={<ModeBadge mode={trading.trading_mode} />} />
        <Row
          label="Live trading hard lock"
          detail="Server setting LIVE_TRADING_ENABLED. Cannot be changed from the dashboard."
          value={
            trading.live_trading_locked ? <Badge tone="positive">Locked</Badge> : <Badge tone="live">Unlocked</Badge>
          }
        />
        <Row
          label="Trading engine"
          detail={trading.engine_detail}
          value={<Badge tone={trading.engine_state === "running" ? "positive" : trading.engine_state === "degraded" ? "warning" : "neutral"}>{trading.engine_state}</Badge>}
        />
        <Row
          label="New orders permitted"
          detail="The combined result of every gate above."
          value={
            trading.new_orders_permitted ? <Badge tone="positive">Yes</Badge> : <Badge tone="neutral">No</Badge>
          }
        />
      </div>
    </Card>
  );
}
