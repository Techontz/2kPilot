"use client";

import { CandlestickChart } from "lucide-react";
import { useState } from "react";
import { CandleChart } from "@/components/charts/CandleChart";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Segmented } from "@/components/ui/Fields";
import { EmptyState, Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { cn } from "@/lib/cn";
import { humanize } from "@/lib/format";
import type { CandlePoint, QuoteRow, Timeframe } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { useAccounts } from "@/features/shared/useAccounts";
import { Datasets } from "./Datasets";

interface QuotesResponse {
  simulated: boolean;
  server_time: string;
  market_open: boolean;
  session: string;
  quotes: QuoteRow[];
}

export function MarketsScreen() {
  const acc = useAccounts();
  const quotes = useApiResource<QuotesResponse>(`/market/quotes?account_id=${acc.selected}`, { enabled: !!acc.selected, intervalMs: 5000 });
  const [chosenSymbol, setSymbol] = useState<string | null>(null);
  const [tf, setTf] = useState<Timeframe>("H1");
  const symbol = chosenSymbol ?? quotes.data?.quotes[0]?.symbol ?? null;
  const candles = useApiResource<{ candles: CandlePoint[]; simulated: boolean; validation: { gaps: number; invalid: number } }>(
    `/market/candles?account_id=${acc.selected}&symbol=${symbol}&timeframe=${tf}&bars=300`,
    { enabled: !!acc.selected && !!symbol, refetchOnFocus: false, intervalMs: 30000 },
  );
  const selectedQuote = quotes.data?.quotes.find((q) => q.symbol === symbol);

  return (
    <>
      <PageHeader
        title="Markets"
        description="Live prices from your broker, price charts, and the historical data used for research."
        actions={acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={(v) => { acc.setSelected(v); setSymbol(null); }} />}
      />
      <div className="space-y-6">
        {acc.data && acc.accounts.length === 0 ? (
          <Card><EmptyState icon={CandlestickChart} title="No account connected">Live prices come from a connected account. Add a Paper or MT5 account on the Brokers page.</EmptyState></Card>
        ) : (
          <>
            {quotes.data?.simulated && <Notice tone="info" title="PAPER / SIMULATION prices">These prices are simulated by the paper broker{quotes.data ? ` (simulated time ${new Date(quotes.data.server_time).toUTCString()})` : ""}. They are not real market quotes.</Notice>}
            {quotes.error && <Notice tone="danger">{quotes.error.message}</Notice>}
            <div className="grid gap-6 lg:grid-cols-3">
              <Card>
                <CardHeader title="Prices" description={quotes.data ? `${humanize(quotes.data.session)} session · market ${quotes.data.market_open ? "open" : "closed"}` : undefined} />
                {!quotes.data && !quotes.error && <CardBody><Loading /></CardBody>}
                <DataTable rows={quotes.data?.quotes ?? null} rowKey={(q) => q.symbol} onRowClick={(q) => setSymbol(q.symbol)} columns={[
                  { key: "s", header: "Symbol", cell: (q) => <span className={cn("font-medium", q.symbol === symbol && "text-accent")}>{q.symbol}{q.watched && <span className="ml-1 text-xs text-fg-subtle">●</span>}</span> },
                  { key: "b", header: "Bid", align: "right", cell: (q) => q.bid },
                  { key: "a", header: "Ask", align: "right", hideBelow: "sm", cell: (q) => q.ask },
                  { key: "sp", header: <Term id="spread" />, align: "right", cell: (q) => <span className={cn(q.age_seconds > 120 && "text-warning")}>{q.spread_pips}</span> },
                ]} />
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader
                  title={symbol ? `${symbol} · ${tf}` : "Chart"}
                  description={selectedQuote ? `Spread ${selectedQuote.spread_pips} pips · price ${selectedQuote.age_seconds}s old` : undefined}
                  action={<Segmented size="sm" label="Timeframe" value={tf} onChange={setTf} options={(["M15", "H1", "H4", "D1"] as Timeframe[]).map((t) => ({ value: t, label: t }))} />}
                />
                <CardBody>
                  {candles.data?.candles.length ? (
                    <>
                      <CandleChart candles={candles.data.candles} digits={selectedQuote?.digits ?? 5} label={`${symbol} ${tf} candles`} />
                      {(candles.data.validation.gaps > 0 || candles.data.validation.invalid > 0) && (
                        <p className="mt-2 text-xs text-warning">Data check: {candles.data.validation.gaps} gap(s), {candles.data.validation.invalid} invalid bar(s).</p>
                      )}
                      {candles.data.simulated && <Badge tone="neutral" className="mt-2">SIMULATED</Badge>}
                    </>
                  ) : candles.error ? <Notice tone="danger">{candles.error.message}</Notice> : <Loading />}
                </CardBody>
              </Card>
            </div>
          </>
        )}
        <Datasets accounts={acc.accounts} />
      </div>
    </>
  );
}
