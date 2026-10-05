"use client";

import { CandlestickChart, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { TextInput } from "@/components/ui/Fields";
import { EmptyState, Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/cn";
import { formatRelative, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Instrument, Quote } from "@/lib/types";

interface InstrumentsResponse {
  account: { id: string; label: string; environment: string };
  provider: string;
  connection_status: string;
  simulated: boolean;
  categories: Record<string, number>;
  instruments: Instrument[];
}

const CATEGORY_LABEL: Record<string, string> = {
  forex: "Forex", commodities: "Commodities", indices: "Indices", crypto: "Crypto", synthetic: "Synthetic indices", stocks: "Stocks", other: "Other",
};

export function MarketsScreen() {
  const { account } = useAppData();
  const [category, setCategory] = useState<string>("all");
  const [search, setSearch] = useState("");
  const list = useApi<InstrumentsResponse>(account ? "/markets/instruments" : null, { account_id: account?.id });
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (list.data?.instruments ?? []).filter((i) =>
      (category === "all" || i.category === category) && (!q || i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q)));
  }, [list.data, category, search]);
  const symbols = visible.slice(0, 40).map((i) => i.name).join(",");
  const quotes = useApi<{ quotes: Record<string, Quote>; errors: Record<string, string> }>(
    account && symbols ? "/markets/quotes" : null, { account_id: account?.id, symbols }, 3000);

  if (!account) return <EmptyAccount />;
  const data = list.data;
  return (
    <div>
      <PageHeader title="Markets" description={data ? `Instruments offered by ${data.provider} on ${data.account.label}. Prices refresh every few seconds.` : undefined} />
      {data?.simulated && <Notice tone="info" className="mb-4">PAPER prices are SYNTHETIC — generated for learning, not real market quotes.</Notice>}
      {list.error && <Notice tone="danger" title="Could not load instruments" className="mb-4">{list.error}</Notice>}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Category">
          {["all", ...Object.keys(data?.categories ?? {})].map((c) => (
            <button key={c} type="button" role="tab" aria-selected={category === c} onClick={() => setCategory(c)}
              className={cn("rounded-full border px-3 py-1 text-sm", category === c ? "border-accent bg-accent/10 text-fg" : "border-line text-fg-muted hover:text-fg")}>
              {c === "all" ? "All" : CATEGORY_LABEL[c] ?? humanize(c)} {c !== "all" && <span className="num text-xs text-fg-subtle">{data?.categories[c]}</span>}
            </button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-fg-subtle" aria-hidden />
          <TextInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search symbol" className="pl-9" aria-label="Search symbol" />
        </div>
      </div>
      <Card>
        {!data && list.loading ? <Loading /> : (
          <DataTable
            caption="Instruments"
            rows={visible}
            rowKey={(r) => r.name}
            empty={<EmptyState icon={CandlestickChart} title="No instruments">The broker has not reported any instruments yet. Check the connection on the Brokers page.</EmptyState>}
            columns={[
              { key: "symbol", header: "Symbol", cell: (r) => (
                <Link href={`/markets/${encodeURIComponent(r.name)}`} className="font-medium text-fg hover:text-accent">
                  {r.canonical !== r.name ? r.canonical : r.name}
                  {r.canonical !== r.name && <span className="ml-1.5 text-xs text-fg-subtle">{r.name}</span>}
                </Link>
              ) },
              { key: "name", header: "Name", hideBelow: "md", cell: (r) => <span className="text-fg-muted">{r.description}</span> },
              { key: "cat", header: "Category", hideBelow: "lg", cell: (r) => <span className="text-fg-muted">{CATEGORY_LABEL[r.category] ?? r.category}</span> },
              { key: "bid", header: "Bid", align: "right", cell: (r) => price(quotes.data?.quotes[r.name]?.bid, r.digits) },
              { key: "ask", header: "Ask", align: "right", cell: (r) => price(quotes.data?.quotes[r.name]?.ask, r.digits) },
              { key: "spread", header: "Spread", align: "right", hideBelow: "sm", cell: (r) => price(quotes.data?.quotes[r.name]?.spread, r.digits) },
              { key: "status", header: "Market", cell: (r) => <MarketStatus open={r.market_open} allowed={r.trade_allowed} /> },
              { key: "provider", header: "Provider", hideBelow: "lg", cell: () => <span className="text-fg-subtle">{data?.provider}</span> },
              { key: "time", header: "Updated", hideBelow: "lg", cell: (r) => <span className="text-xs text-fg-subtle">{formatRelative(quotes.data?.quotes[r.name]?.time)}</span> },
            ]}
          />
        )}
      </Card>
      {visible.length > 40 && <p className="mt-2 text-xs text-fg-subtle">Live prices are shown for the first 40 results — narrow the search to see others.</p>}
    </div>
  );
}

function price(value: string | undefined, digits: number): string {
  return value === undefined ? "—" : Number(value).toFixed(Math.min(digits, 6));
}

export function MarketStatus({ open, allowed }: { open: boolean | null; allowed: boolean }) {
  if (!allowed) return <Badge tone="negative">Suspended</Badge>;
  if (open === null) return <Badge tone="neutral">—</Badge>;
  return open ? <Badge tone="positive" dot>Open</Badge> : <Badge tone="neutral" dot>Closed</Badge>;
}

export function EmptyAccount() {
  return (
    <Card>
      <EmptyState icon={CandlestickChart} title="Connect an account first" action={<Link href="/brokers/new" className="text-sm text-accent hover:underline">Add broker</Link>}>
        Markets show the instruments and live prices of a connected broker account.
      </EmptyState>
    </Card>
  );
}
