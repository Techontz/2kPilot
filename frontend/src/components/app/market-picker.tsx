"use client";

import { RefreshCw, Search } from "lucide-react";
import { useId, useMemo, useState, type KeyboardEvent } from "react";
import { Notice } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { groupMarkets, type InstrumentsResponse, marketLabel } from "@/lib/markets";
import type { Instrument } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The account's markets, plus a way to fetch them from the broker again. */
export function useInstruments(accountId: string | null | undefined) {
  const resource = useApi<InstrumentsResponse>(accountId ? "/markets/instruments" : null, { account_id: accountId });
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    if (!accountId) return;
    setRefreshing(true);
    try {
      resource.set(await api<InstrumentsResponse>("/markets/instruments", { query: { account_id: accountId, refresh: 1 } }));
    } catch {
      await resource.reload(); // shows the request's error the usual way
    } finally {
      setRefreshing(false);
    }
  };
  return {
    instruments: resource.data?.instruments ?? null,
    loading: resource.loading,
    error: resource.error ?? resource.data?.sync_error ?? null,
    refresh: () => void refresh(),
    refreshing,
  };
}

interface MarketPickerProps {
  /** The markets the account's broker reports (null while loading). */
  instruments: Instrument[] | null;
  value: string;
  onChange: (symbol: string) => void;
  loading?: boolean;
  /** Why the list could not be (re)fetched from the broker. */
  error?: string | null;
  /** Fetch the list from the broker again. */
  onRefresh?: () => void;
  refreshing?: boolean;
  /** Why a market can't be picked here (null: it can). */
  unavailable?: (i: Instrument) => string | null;
  label?: string;
  emptyText?: string;
}

/**
 * Searchable, grouped market list (Volatility indices first). Only markets the
 * broker reported are listed; closed or suspended ones are shown but explained.
 */
export function MarketPicker({ instruments, value, onChange, loading, error, onRefresh, refreshing, unavailable, label = "Market", emptyText }: MarketPickerProps) {
  const uid = useId();
  const [query, setQuery] = useState("");
  const groups = useMemo(() => groupMarkets(instruments ?? [], query), [instruments, query]);
  const options = useMemo(() => groups.flatMap((g) => g.instruments), [groups]);
  const reason = (i: Instrument) => unavailable?.(i) ?? (i.trade_allowed ? null : "Suspended by the broker");
  const [activeName, setActiveName] = useState<string | null>(null);
  const active = options.find((i) => i.name === activeName) ?? options.find((i) => i.name === value) ?? options[0] ?? null;
  const optionId = (i: Instrument) => `${uid}-opt-${i.name}`;

  const pick = (i: Instrument) => {
    if (!reason(i)) onChange(i.name);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!options.length) return;
    const at = active ? options.indexOf(active) : -1;
    const move = (to: number) => {
      const next = options[Math.max(0, Math.min(options.length - 1, to))]!;
      setActiveName(next.name);
      document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" });
    };
    if (e.key === "ArrowDown") { e.preventDefault(); move(at + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(at - 1); }
    else if (e.key === "Enter" && active) { e.preventDefault(); pick(active); }
  };

  if (loading && !instruments) return <Skeleton className="h-48 w-full" />;
  const total = instruments?.length ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" />
          <Input
            role="combobox"
            aria-label={`Search ${label.toLowerCase()}s`}
            aria-expanded
            aria-controls={`${uid}-list`}
            aria-activedescendant={active ? optionId(active) : undefined}
            aria-autocomplete="list"
            className="pl-9"
            placeholder={total ? `Search ${total} markets — e.g. "Volatility 75" or "R_75"` : "Search markets"}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveName(null); }}
            onKeyDown={onKeyDown}
            disabled={!total}
            autoComplete="off"
          />
        </div>
        {onRefresh && (
          <Button type="button" variant="outline" size="icon" className="size-10 max-sm:size-11" onClick={onRefresh} disabled={refreshing} aria-label="Fetch markets from the broker again" title="Fetch markets from the broker again">
            <RefreshCw aria-hidden className={cn(refreshing && "animate-spin")} />
          </Button>
        )}
      </div>

      {error && (
        <Notice tone="warning" title={total ? "Couldn't refresh markets from the broker" : "Couldn't load markets from the broker"}>
          {error}{total ? " Showing the last list received." : " Try again in a moment."}
        </Notice>
      )}

      {total > 0 && (
        <div id={`${uid}-list`} role="listbox" aria-label={label} className="max-h-64 overflow-y-auto rounded-md border border-line">
          {groups.length === 0 && <p className="px-3 py-4 text-sm text-fg-muted">No market matches “{query}”.</p>}
          {groups.map((g) => (
            <div key={g.key} role="group" aria-labelledby={`${uid}-grp-${g.key}`}>
              <p id={`${uid}-grp-${g.key}`} className="sticky top-0 z-10 bg-card px-3 pt-2.5 pb-1 text-xs font-medium tracking-wide text-fg-subtle uppercase">
                {g.label} <span className="num normal-case">({g.instruments.length})</span>
              </p>
              {g.instruments.map((i) => {
                const why = reason(i);
                const selected = i.name === value;
                return (
                  <div
                    key={i.name}
                    id={optionId(i)}
                    role="option"
                    aria-selected={selected}
                    aria-disabled={why ? true : undefined}
                    onClick={() => pick(i)}
                    onMouseEnter={() => setActiveName(i.name)}
                    className={cn(
                      "flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm",
                      active?.name === i.name && "bg-surface-raised",
                      selected && "bg-primary/10 font-medium text-fg",
                      why && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <span className="min-w-0 truncate text-fg">{marketLabel(i)}</span>
                    <span className="flex shrink-0 items-center gap-2 text-xs text-fg-subtle">
                      {why ? <span className="text-warning">{why}</span> : i.market_open === false ? <span>Closed now</span> : null}
                      <span className="num">{i.name}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {!total && !error && <p className="text-sm text-fg-muted">{emptyText ?? "This account's broker hasn't reported any markets yet."}</p>}
    </div>
  );
}
