"use client";

import { Activity } from "lucide-react";
import Link from "next/link";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { ConnectionBadge, EmptyState, EnvBadge, Loading, Notice, SideBadge } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { formatPrice, formatTime, humanize } from "@/lib/format";
import { deriveRobotStatus, type Tone } from "@/lib/status";
import type { SignalRow, TradingAccount } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { ModeSelector } from "./ModeSelector";

const SIGNAL_TONE: Record<string, Tone> = {
  EXECUTED: "positive", APPROVED: "info", REJECTED: "warning", FAILED: "negative", SKIPPED: "neutral", NEW: "info",
};

export function TradingScreen() {
  const { status, error } = useSystemStatus();
  const accounts = useApiResource<TradingAccount[]>("/accounts");
  const signals = useApiResource<SignalRow[]>("/signals?limit=25");
  useLiveRefresh(["journal", "broker", "account"], () => {
    void signals.reload();
    void accounts.reload();
  });
  if (!status) return error ? <Notice tone="danger">{error.message}</Notice> : <Loading />;
  const robot = deriveRobotStatus(status.trading);

  return (
    <>
      <PageHeader
        title="Trading"
        description="Where the robot may trade and what it is doing now. A strategy can only propose a trade; the risk engine decides."
      />
      <div className="space-y-6">
        <ModeSelector trading={status.trading} />
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title="Automation engine" action={<Badge tone={robot.tone} dot>{robot.label}</Badge>} />
            <CardBody className="space-y-3">
              <p className="text-sm text-fg-muted">{status.trading.engine_detail}</p>
              <p className="text-xs text-fg-subtle">
                Every couple of seconds the engine reconciles orders and positions with each broker, then evaluates enabled strategies on newly
                closed bars: market data → strategy → risk engine → execution → broker.
              </p>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Accounts" action={<Link href="/brokers" className="text-xs text-accent hover:underline">Manage</Link>} />
            <CardBody className="py-2">
              {accounts.data?.length === 0 && <p className="py-3 text-sm text-fg-subtle">No accounts yet.</p>}
              <ul className="divide-y divide-line">
                {accounts.data?.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <span className="flex items-center gap-2 text-sm text-fg">{a.label} <EnvBadge env={a.environment} /></span>
                    <span className="flex items-center gap-2">
                      {a.connection && <ConnectionBadge status={a.connection.status} />}
                      <Badge tone={a.trading_enabled ? "positive" : "neutral"}>{a.trading_enabled ? "Trading on" : "Trading off"}</Badge>
                    </span>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>
        <Card>
          <CardHeader title="Latest signals" description="Every signal and the risk engine's decision. Rejected signals are normal — they are the risk engine doing its job." />
          {signals.data?.length === 0 ? (
            <EmptyState icon={Activity} title="No signals yet">Signals appear when an enabled strategy finds a setup on a newly closed bar.</EmptyState>
          ) : (
            <DataTable
              rows={signals.data}
              loading={signals.loading}
              error={signals.error?.message}
              rowKey={(s) => s.id}
              columns={[
                { key: "t", header: "Time", cell: (s) => <span className="text-xs text-fg-muted">{formatTime(s.created_at)}</span> },
                { key: "sig", header: "Signal", cell: (s) => <span className="flex items-center gap-2"><SideBadge side={s.side} /><span className="font-medium">{s.symbol}</span><span className="text-xs text-fg-subtle">{s.timeframe}</span></span> },
                { key: "entry", header: "Entry / SL / TP", hideBelow: "md", cell: (s) => <span className="num text-xs">{formatPrice(s.entry_price, s.symbol)} / {formatPrice(s.stop_loss, s.symbol)} / {formatPrice(s.take_profit, s.symbol)}</span> },
                { key: "status", header: "Decision", cell: (s) => <Badge tone={SIGNAL_TONE[s.status] ?? "neutral"}>{humanize(s.status)}</Badge> },
                { key: "why", header: "Reason", hideBelow: "sm", cell: (s) => <span className="text-xs text-fg-muted">{s.rejection_reason?.replace("Trade rejected: ", "") ?? (s.volume ? `${s.volume} lots, risk ${s.risk_amount}` : "—")}</span> },
              ]}
            />
          )}
        </Card>
      </div>
    </>
  );
}
