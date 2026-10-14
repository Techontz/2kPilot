"use client";

import { Pill, type Tone } from "@/components/app/badges";
import { PnlText } from "@/components/app/money";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FAMILY_LABEL } from "@/lib/contracts";
import { formatSignedCurrency } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Scorecard as ScorecardData, ScorecardRow, ScorecardVerdict } from "@/lib/types";
import { cn } from "@/lib/utils";

const VERDICT: Record<ScorecardVerdict, { tone: Tone; label: string }> = {
  PROFITABLE: { tone: "positive", label: "Profitable" },
  LOSING: { tone: "negative", label: "Losing" },
  NO_EDGE: { tone: "warning", label: "No edge yet" },
  TOO_EARLY: { tone: "neutral", label: "Too early" },
};

/**
 * The honest scoreboard: each strategy's real win rate against the win rate it
 * needs to break even, and a verdict that doesn't mistake a lucky run for an edge.
 */
export function Scorecard() {
  const { account } = useAppData();
  const card = useApi<ScorecardData>(account ? "/analytics/scorecard" : null, { account_id: account?.id }, 60_000);
  const rows = card.data?.account_id === account?.id ? card.data?.rows ?? [] : [];
  if (!account || rows.length === 0) return null;

  return (
    <section aria-labelledby="scorecard-title">
      <Card>
        <CardHeader>
          <CardTitle id="scorecard-title">Scorecard · {account.label}</CardTitle>
          <CardDescription>
            Real results from this account&apos;s closed trades. A strategy only makes money if it wins more often than its
            break-even rate. Judge it after {card.data?.min_trades ?? 30}+ trades, not after a good or bad day.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-line">
            {rows.map((r) => <ScoreRow key={`${r.strategy_id}-${r.symbol}-${r.contract_family}`} row={r} currency={account.currency} />)}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

function ScoreRow({ row: r, currency }: { row: ScorecardRow; currency: string }) {
  const v = VERDICT[r.verdict];
  const ahead = r.break_even_win_rate !== null ? r.win_rate - r.break_even_win_rate : null;
  return (
    <li className="grid gap-3 py-4 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-bold text-fg">{r.strategy}</p>
          <span className="text-sm text-fg-muted">{r.symbol} · {FAMILY_LABEL[r.contract_family] ?? r.contract_family}</span>
          <Pill tone={v.tone} dot>{v.label}</Pill>
        </div>
        <p className="mt-1 text-sm text-fg-muted">{r.verdict_text}</p>
      </div>
      <dl className="grid grid-cols-4 gap-x-4 gap-y-1 text-right text-sm sm:min-w-[24rem]">
        <Stat label="Trades" value={String(r.trades)} />
        <Stat label="Won" value={`${r.win_rate}%`} className={ahead === null ? undefined : ahead >= 0 ? "text-positive" : "text-negative"} />
        <Stat label="Needed" value={r.break_even_win_rate !== null ? `${r.break_even_win_rate}%` : "—"} />
        <div>
          <dt className="text-xs text-fg-subtle">Net</dt>
          <dd><PnlText value={r.net_pnl} currency={currency} className="font-semibold" /></dd>
        </div>
        <p className="col-span-4 text-xs text-fg-subtle">
          {formatSignedCurrency(r.expectancy, currency)} per trade on average
        </p>
      </dl>
    </li>
  );
}

function Stat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className={cn("num font-semibold text-fg", className)}>{value}</dd>
    </div>
  );
}
