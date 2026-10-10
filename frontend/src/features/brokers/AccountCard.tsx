"use client";

import { MoreHorizontal, PlugZap, RefreshCw, Trash2, Unplug } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConnectionBadge, EnvBadge, Pill } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { Money } from "@/components/app/money";
import { Term } from "@/components/app/term";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { api, ApiError } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Account } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCENT: Record<Account["environment"], string> = {
  PAPER: "border-t-fg-subtle",
  DEMO: "border-t-demo",
  LIVE: "border-t-live",
  UNKNOWN: "border-t-warning",
};

type Busy = "sync" | "reconnect" | "disconnect" | "remove" | null;

/** One broker account: what the broker reported, and the connection actions. */
export function AccountCard({ account, onChange }: { account: Account; onChange: () => void }) {
  const [busy, setBusy] = useState<Busy>(null);
  const [confirm, setConfirm] = useState<"disconnect" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (what: Exclude<Busy, null>, fn: () => Promise<unknown>, success: string): Promise<boolean> => {
    setBusy(what);
    setError(null);
    try {
      await fn();
      toast.success(success);
      onChange();
      return true;
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      setError(message);
      if (!confirm) toast.error("That did not work", { description: message });
      return false;
    } finally {
      setBusy(null);
    }
  };

  const sync = () => void run("sync", () => api(`/accounts/${account.id}/sync`, { method: "POST" }), "Account synced");
  const reconnect = () => void run("reconnect", () => api(`/brokers/${account.connection_id}/reconnect`, { method: "POST" }), "Reconnecting…");
  const disconnect = async () => {
    if (await run("disconnect", () => api(`/brokers/${account.connection_id}/disconnect`, { method: "POST" }), "Disconnected")) setConfirm(null);
  };
  const remove = async () => {
    let archived = false;
    const ok = await run("remove", async () => {
      const res = await api<{ result: string }>(`/brokers/${account.connection_id}`, { method: "DELETE" });
      archived = res?.result === "broker.archived";
    }, "Broker removed");
    if (ok) {
      setConfirm(null);
      if (archived) toast.info("Archived instead of deleted", { description: "This account has trading history, so it was kept (credentials deleted, trading off)." });
    }
  };

  const connected = account.connection_status === "CONNECTED";
  const archived = !account.connection_enabled;

  return (
    <Card role="article" aria-label={`${account.label} account`} aria-busy={busy !== null}
      className={cn("h-full gap-0 border-t-2 py-0", ACCENT[account.environment])}>
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <div className="flex min-w-0 items-center gap-3.5">
          <span aria-hidden className={cn("flex size-12 shrink-0 items-center justify-center rounded-md text-lg font-extrabold text-white shadow-raised",
            account.environment === "LIVE" ? "bg-[linear-gradient(160deg,#d6392e,#8a1a14)]" : account.environment === "DEMO" ? "bg-brand" : "bg-[linear-gradient(160deg,#3c3c40,#141416)]")}>
            {account.label.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-fg-subtle">{account.broker}</p>
            <h3 className="truncate text-lg font-extrabold tracking-tight text-fg">{account.label}</h3>
            <p className="mono-id truncate text-[11px] text-fg-subtle">{account.broker_account_id}{account.server ? ` · ${account.server}` : ""}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <EnvBadge env={account.environment} />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${account.label}`} disabled={busy !== null}>
                <MoreHorizontal aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem onSelect={sync}><RefreshCw aria-hidden /> Sync now</DropdownMenuItem>
              <DropdownMenuItem onSelect={reconnect}><PlugZap aria-hidden /> Reconnect</DropdownMenuItem>
              {account.connection_enabled && (
                <DropdownMenuItem onSelect={() => { setError(null); setConfirm("disconnect"); }}><Unplug aria-hidden /> Disconnect…</DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => { setError(null); setConfirm("remove"); }}><Trash2 aria-hidden /> Remove…</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="space-y-1 px-5 pt-4" aria-live="polite">
        <ConnectionBadge status={account.connection_status} />
        {account.connection_detail && !connected && <p className="text-xs text-fg-muted">{account.connection_detail}</p>}
      </div>

      <dl className="mx-5 my-4 grid grid-cols-2 gap-x-4 gap-y-3 rounded-md bg-surface-raised p-4 text-sm">
        <Item label={<Term id="balance" />} value={<Money value={account.balance} currency={account.currency} />} />
        <Item label={<Term id="equity" />} value={<Money value={account.equity} currency={account.currency} />} />
        <Item label="Last sync" value={<span className="num">{formatRelative(account.synced_at)}</span>} />
        <Item label="Trading" value={account.trading_enabled ? <Pill tone="positive">Enabled</Pill> : <Pill>Off</Pill>} />
      </dl>

      <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-line px-5 py-3.5">
        <Button size="sm" variant="outline" onClick={sync} disabled={busy !== null}>
          <RefreshCw aria-hidden className={cn(busy === "sync" && "motion-safe:animate-spin")} /> {busy === "sync" ? "Syncing…" : "Sync now"}
        </Button>
        {(!connected || archived) && (
          <Button size="sm" variant="outline" onClick={reconnect} disabled={busy !== null}>
            <PlugZap aria-hidden /> {busy === "reconnect" ? "Reconnecting…" : "Reconnect"}
          </Button>
        )}
        {account.capabilities?.pending_orders === false && <Pill>Market orders only</Pill>}
      </div>
      {error && !confirm && <p role="alert" className="px-5 pb-3 text-xs text-negative">{error}</p>}

      <ConfirmDialog open={confirm === "disconnect"} onOpenChange={(o) => !o && setConfirm(null)} title={`Disconnect ${account.label}?`}
        confirmLabel="Disconnect" destructive busy={busy === "disconnect"} error={error} onConfirm={() => void disconnect()}>
        <p>The engine stops watching this account and trading on it is switched off. Open positions stay open at the broker. You can reconnect later.</p>
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "remove"} onOpenChange={(o) => !o && setConfirm(null)} title={`Remove ${account.label}?`}
        confirmLabel="Remove" destructive busy={busy === "remove"} error={error} onConfirm={() => void remove()}>
        <p>Its stored credentials are deleted. If the account has trading history it is archived instead of deleted, so your history and results stay complete.</p>
        <p>Close any open positions on it first.</p>
      </ConfirmDialog>
    </Card>
  );
}

function Item({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 truncate font-bold text-fg">{value}</dd>
    </div>
  );
}
