"use client";

import { AlertOctagon, Pencil, Plus, ShieldCheck, ShieldHalf, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { EnvBadge } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { CardsSkeleton, EmptyState, ErrorState, ListSkeleton, Notice, SectionHeader } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { api, ApiError } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { limitSentences } from "@/lib/liveAuth";
import type { RiskProfile, RiskUsage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ProfileEditor } from "./ProfileEditor";

/** Settings → Risk limits: the limits every trade must pass, per profile. */
export function RiskScreen() {
  const { account, accounts, reloadAccounts } = useAppData();
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  const [editing, setEditing] = useState<RiskProfile | "new" | null>(null);
  const [deleting, setDeleting] = useState<RiskProfile | null>(null);
  const del = useAction();
  const currency = account?.currency ?? null;

  const remove = async () => {
    if (!deleting) return;
    const ok = await del.run(() => api(`/risk/profiles/${deleting.id}`, { method: "DELETE" }));
    if (ok !== null) {
      toast.success("Risk profile deleted", { description: deleting.name });
      setDeleting(null);
      void profiles.reload();
    }
  };

  return (
    <div className="space-y-8">
      <section>
        <SectionHeader
          title="Risk profiles"
          description="Every automated and manual trade must pass its account's limits. A limit that cannot be checked blocks the trade."
          actions={<Button onClick={() => setEditing("new")}><Plus aria-hidden /> New profile</Button>}
        />
        {profiles.error && !profiles.data ? (
          <ErrorState message={profiles.error} onRetry={() => void profiles.reload()} />
        ) : !profiles.data ? (
          <CardsSkeleton count={2} className="xl:grid-cols-2" />
        ) : profiles.data.length === 0 ? (
          <Card>
            <EmptyState icon={ShieldHalf} title="No risk profiles" action={<Button onClick={() => setEditing("new")}><Plus aria-hidden /> New profile</Button>}>
              Create a profile, then assign it to an account in Settings → Accounts. An account without one cannot trade.
            </EmptyState>
          </Card>
        ) : (
          <ul className="grid gap-4 lg:grid-cols-2">
            {profiles.data.map((p) => {
              const users = (accounts ?? []).filter((a) => a.risk_profile?.id === p.id);
              return (
                <li key={p.id} className="min-w-0">
                  <Card role="article" aria-label={`${p.name} risk profile`} className="h-full gap-0 py-0">
                    <CardContent className="space-y-3 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="truncate font-semibold text-fg">{p.name}</h3>
                          <p className="text-xs text-fg-muted">
                            {(p.accounts_count ?? users.length) === 0
                              ? "Not used by any account"
                              : `Used by ${p.accounts_count ?? users.length} account${(p.accounts_count ?? users.length) === 1 ? "" : "s"}`}
                            {users.length > 0 && `: ${users.map((a) => a.label).join(", ")}`}
                          </p>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          <Button size="sm" variant="outline" onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}><Pencil aria-hidden /> Edit</Button>
                          <Button size="icon-sm" variant="ghost" onClick={() => { del.reset(); setDeleting(p); }} aria-label={`Delete ${p.name}`}>
                            <Trash2 aria-hidden />
                          </Button>
                        </div>
                      </div>
                      <ul className="space-y-1 text-sm">
                        {limitSentences(p, currency).map((s) => (
                          <li key={s.key} className={cn(s.tone === "warning" ? "text-fg-subtle" : "text-fg")}>{s.text}</li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {account && <UsageCard accountId={account.id} />}
      <ClosePositions />

      {editing !== null && (
        <ProfileEditor
          key={editing === "new" ? "new" : editing.id}
          profile={editing === "new" ? null : editing}
          currency={currency}
          open
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void profiles.reload();
            void reloadAccounts();
          }}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "profile"}?`}
        confirmLabel="Delete profile"
        destructive
        busy={del.busy}
        error={del.error}
        onConfirm={() => void remove()}
      >
        <p>This cannot be undone. A profile that is still assigned to an account cannot be deleted, and the Beginner profile is always kept.</p>
      </ConfirmDialog>
    </div>
  );
}

/** How much of each limit the selected account has used today. */
function UsageCard({ accountId }: { accountId: string }) {
  const usage = useApi<RiskUsage>(`/risk/usage/${accountId}`, undefined, 15_000);
  const data = usage.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Limits used today{data && <><span className="text-fg-muted">·</span> {data.account.label} <EnvBadge env={data.account.environment} /></>}
        </CardTitle>
        <CardDescription>{data ? (data.profile ? `Profile: ${data.profile.name}` : "No risk profile assigned — this account cannot trade.") : "For the account you are using."}</CardDescription>
      </CardHeader>
      <CardContent>
        {usage.error && !data ? (
          <ErrorState message={usage.error} onRetry={() => void usage.reload()} />
        ) : !data ? (
          <ListSkeleton rows={2} />
        ) : data.usage.length === 0 ? (
          <p className="text-sm text-fg-muted">Nothing to show yet.</p>
        ) : (
          <ul className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {data.usage.map((u) => {
              const pct = u.used !== null && u.limit ? Math.min(100, Math.round((u.used / u.limit) * 100)) : 0;
              const suffix = u.unit === "%" ? "%" : u.unit ? ` ${u.unit}` : "";
              return (
                <li key={u.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="text-fg-muted">{u.label}</span>
                    <span className="num text-fg">
                      {u.used === null ? "—" : `${u.used}${suffix}`}
                      <span className="text-fg-subtle"> / {u.limit === null ? "no limit" : `${u.limit}${suffix}`}</span>
                    </span>
                  </div>
                  <Progress value={pct} aria-label={`${u.label}: ${pct}% of the limit used`}
                    className={cn(pct >= 100 ? "[&>*]:bg-negative" : pct >= 75 ? "[&>*]:bg-warning" : "")} />
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** The separate, deliberate emergency action. STOP TRADING alone never closes positions. */
function ClosePositions() {
  const { reloadStatus } = useAppData();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ closed: number; failed: unknown[] } | null>(null);
  const inputId = useId();

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ closed: number; failed: unknown[] }>("/trading/close-positions", { method: "POST", body: { confirm: true, reason: "Close positions from Settings → Risk limits" } });
      setResult(res);
      setOpen(false);
      setTyped("");
      toast.success(`Closed ${res.closed} position${res.closed === 1 ? "" : "s"}`);
      void reloadStatus();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><AlertOctagon className="size-4 text-negative" aria-hidden /> Emergency: close all positions</CardTitle>
        <CardDescription>Stops your trading, then closes every open trade on all your accounts at the market price. Stop trading alone never closes trades.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button variant="destructive" onClick={() => { setError(null); setOpen(true); }}>Close all positions…</Button>
        {result && (
          <Notice tone={result.failed.length ? "warning" : "success"}>
            Closed {result.closed} position(s){result.failed.length ? `; ${result.failed.length} could not be closed — see Notifications` : ""}.
          </Notice>
        )}
        <p className="flex items-center gap-1.5 text-xs text-fg-subtle"><ShieldCheck className="size-3.5" aria-hidden /> Recorded in the audit log with your name and the time.</p>
      </CardContent>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close all your open positions?</AlertDialogTitle>
            <AlertDialogDescription>
              Your trading is stopped first. Then every open position is closed at the current market price. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={inputId}>Type CLOSE to confirm</Label>
            <Input id={inputId} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </div>
          {error && <p role="alert" className="text-sm text-negative">{error}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button variant="destructive" onClick={() => void run()} disabled={busy || typed.trim() !== "CLOSE"}>
              {busy ? "Closing…" : "Close all positions"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
