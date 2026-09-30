"use client";

import { Gauge } from "lucide-react";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, Loading, Meter, Notice } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { formatMoney, formatPct, formatTime } from "@/lib/format";
import type { RiskUsage, TradingAccount } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

export function AccountUsage({ account }: { account: TradingAccount }) {
  const usage = useApiResource<RiskUsage>(`/risk/usage/${account.id}`);
  useLiveRefresh(["journal", "account"], () => void usage.reload(), 1500);
  const u = usage.data;
  const n = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v));
  return (
    <Card>
      <CardHeader title={`Limits in use · ${account.label}`} description={u?.profile ? `Profile: ${u.profile.name}` : undefined} />
      <CardBody className="space-y-5">
        {!u && <Loading />}
        {u && !u.profile && (
          <EmptyState icon={Gauge} title="No risk profile">
            This account cannot trade until a risk profile is assigned on the Brokers page.
          </EmptyState>
        )}
        {u?.error && <Notice tone="warning">{u.error}</Notice>}
        {u?.live && u.daily_loss && u.drawdown && u.weekly_loss && u.open_risk && u.positions && u.trades_today && (
          <>
            <Meter label="Daily loss" used={u.daily_loss.pct} limit={n(u.daily_loss.limit_pct)}
              detail={`${formatPct(u.daily_loss.pct)} of ${u.daily_loss.limit_pct ? `${u.daily_loss.limit_pct}%` : "no limit"} · ${formatMoney(u.daily_loss.amount, u.currency)}`} />
            <Meter label="Weekly loss" used={u.weekly_loss.pct} limit={n(u.weekly_loss.limit_pct)}
              detail={`${formatPct(u.weekly_loss.pct)} of ${u.weekly_loss.limit_pct ? `${u.weekly_loss.limit_pct}%` : "no limit"}`} />
            <Meter label={<Term id="drawdown" />} used={u.drawdown.pct} limit={n(u.drawdown.limit_pct)}
              detail={`${formatPct(u.drawdown.pct)} of ${u.drawdown.limit_pct ? `${u.drawdown.limit_pct}%` : "no limit"} · peak ${formatMoney(u.drawdown.peak_equity)}`} />
            <Meter label={<Term id="openRisk" />} used={u.open_risk.pct} limit={n(u.open_risk.limit_pct)}
              detail={u.open_risk.unknown ? "unknown (external position)" : `${formatMoney(u.open_risk.amount, u.currency)} · ${formatPct(u.open_risk.pct)} of ${u.open_risk.limit_pct ?? "∞"}%`} />
            <Meter label="Open positions" used={u.positions.open} limit={u.positions.max} detail={`${u.positions.open} of ${u.positions.max ?? "∞"} · ${u.positions.lots} lots`} />
            <Meter label="Trades today" used={u.trades_today.count} limit={u.trades_today.max} detail={`${u.trades_today.count} of ${u.trades_today.max ?? "∞"}`} />
            {u.consecutive_losses && u.consecutive_losses.count > 0 && (
              <p className="text-xs text-fg-subtle">{u.consecutive_losses.count} losing trade(s) in a row{u.consecutive_losses.cooldown_after ? ` — cooldown starts at ${u.consecutive_losses.cooldown_after}` : ""}.</p>
            )}
          </>
        )}
        {u && u.recent_violations.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Recent rejected trades</p>
            <ul className="divide-y divide-line">
              {u.recent_violations.slice(0, 6).map((s) => (
                <li key={s.id} className="py-2 text-sm">
                  <p className="text-fg">{s.side} {s.symbol} — <span className="text-fg-muted">{s.rejection_reason?.replace("Trade rejected: ", "")}</span></p>
                  <p className="text-xs text-fg-subtle">{formatTime(s.created_at)}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
