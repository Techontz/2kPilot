"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CandleChart } from "@/components/charts/CandleChart";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/Fields";
import { KeyValue, Loading, Notice } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { useApi } from "@/lib/hooks";
import type { Candle, Quote, SymbolSpec } from "@/lib/types";
import { EmptyAccount, MarketStatus } from "./MarketsScreen";

const TIMEFRAMES = ["M15", "H1", "H4", "D1"] as const;

export function InstrumentScreen({ symbol }: { symbol: string }) {
  const { account } = useAppData();
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("H1");
  const detail = useApi<{ symbol: SymbolSpec; quote: Quote | null; candles: Candle[]; provider: string; simulated: boolean }>(
    account ? `/markets/instruments/${encodeURIComponent(symbol)}` : null, { account_id: account?.id, timeframe }, 5000);
  if (!account) return <EmptyAccount />;
  const d = detail.data;
  return (
    <div className="space-y-6">
      <Link href="/markets" className="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg"><ArrowLeft className="size-4" aria-hidden /> Markets</Link>
      {detail.error && !d && <Notice tone="danger" title="Instrument unavailable">{detail.error}</Notice>}
      {!d ? <Loading /> : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{d.symbol.canonical}</h1>
              <p className="text-sm text-fg-muted">{d.symbol.description} · {d.provider}{d.simulated && " · SYNTHETIC prices"}</p>
            </div>
            <div className="flex items-center gap-6">
              <PriceBox label="Bid" value={d.quote?.bid} digits={d.symbol.digits} />
              <PriceBox label="Ask" value={d.quote?.ask} digits={d.symbol.digits} />
              <Link href={`/trade?symbol=${encodeURIComponent(d.symbol.name)}`}><Button variant="primary">Trade</Button></Link>
            </div>
          </div>
          <div className="grid gap-6 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Price" action={<Segmented size="sm" label="Timeframe" value={timeframe} onChange={setTimeframe} options={TIMEFRAMES.map((t) => ({ value: t, label: t }))} />} />
              <CardBody>
                {d.candles.length ? <CandleChart candles={d.candles} digits={d.symbol.digits} label={`${d.symbol.canonical} ${timeframe} candles`} /> : <p className="py-10 text-center text-sm text-fg-muted">No candles available from the broker for this timeframe.</p>}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Specification" description="As reported by the broker" />
              <CardBody>
                <KeyValue items={[
                  ["Market", <MarketStatus key="m" open={d.symbol.market_open} allowed={d.symbol.trade_allowed} />],
                  [<Term key="s" id="spread" />, d.quote ? Number(d.quote.spread).toFixed(d.symbol.digits) : "—"],
                  [<Term key="p" id="pip" />, d.symbol.pip_size],
                  [<Term key="l" id="lot" />, `${Number(d.symbol.contract_size).toLocaleString()} units`],
                  ["Min / step / max volume", `${Number(d.symbol.volume_min)} / ${Number(d.symbol.volume_step)} / ${Number(d.symbol.volume_max)}`],
                  ["Base / quote currency", `${d.symbol.base_currency} / ${d.symbol.quote_currency}`],
                  ["Category", d.symbol.category],
                ]} />
              </CardBody>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function PriceBox({ label, value, digits }: { label: string; value?: string; digits: number }) {
  return (
    <div className="text-right">
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className="num text-lg font-semibold text-fg">{value ? Number(value).toFixed(digits) : "—"}</p>
    </div>
  );
}
