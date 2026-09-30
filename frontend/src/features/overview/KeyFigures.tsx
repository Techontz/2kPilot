import { StatCard } from "@/components/ui/StatCard";
import { Pnl } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { formatMoney, formatPct, formatPnl } from "@/lib/format";
import type { Overview } from "@/lib/types";

/** The numbers a trader checks first. Dashes mean "no account yet", never zero. */
export function KeyFigures({ data }: { data: Overview }) {
  const t = data.totals;
  const none = data.accounts.length === 0;
  const hint = none ? "No account connected" : undefined;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard label={<Term id="balance" />} value={formatMoney(t.balance)} hint={hint ?? data.currency} />
      <StatCard label={<Term id="equity" />} value={formatMoney(t.equity)} hint={hint ?? "Balance + open P/L"} />
      <StatCard
        label={<Term id="pnl">Today&apos;s P/L</Term>}
        value={<Pnl value={t.today_pnl}>{formatPnl(t.today_pnl)}</Pnl>}
        hint={hint ?? `${t.trades_today} trade${t.trades_today === 1 ? "" : "s"} today`}
      />
      <StatCard
        label={<Term id="openRisk" />}
        value={t.open_risk_unknown ? "Unknown" : formatMoney(t.open_risk)}
        valueClassName={t.open_risk_unknown ? "text-warning" : undefined}
        hint={hint ?? `${t.open_positions} open position${t.open_positions === 1 ? "" : "s"}`}
      />
      <StatCard label="Open P/L" value={<Pnl value={t.open_pnl}>{formatPnl(t.open_pnl)}</Pnl>} hint={hint ?? "Unrealised"} />
      <StatCard label={<Term id="drawdown">Current drawdown</Term>} value={t.max_drawdown_pct === null ? "—" : formatPct(t.max_drawdown_pct)} hint={hint ?? "Worst account, from its peak"} />
      <StatCard label="Active strategies" value={data.active_strategies} hint="Enabled assignments" />
      <StatCard label="Today's trades" value={t.trades_today} hint="Opened since 00:00 UTC" />
    </div>
  );
}
