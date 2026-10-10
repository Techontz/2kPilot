"use client";

import { Activity, Cable, OctagonPause, Play, ScrollText, Server } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { toast } from "sonner";
import { ConnectionBadge, EnvBadge, Pill, type Tone } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { EmptyState, ErrorState, ListSkeleton, Notice } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
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
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { describeAuditAction, formatDateTime, formatRelative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { engineHealthView } from "@/lib/status";
import type { AuditEntry, EngineState, EngineSupervisor, Paginated, SystemStatus } from "@/lib/types";

const ENGINE: Record<EngineState, { tone: Tone; label: string }> = {
  running: { tone: "positive", label: "Running" },
  degraded: { tone: "warning", label: "Degraded" },
  offline: { tone: "warning", label: "No heartbeat" },
};

const SUPERVISOR: Record<EngineSupervisor["state"], { tone: Tone; label: string }> = {
  running: { tone: "positive", label: "Running" },
  degraded: { tone: "warning", label: "Running · attention" },
  stale: { tone: "warning", label: "Not responding" },
  not_started: { tone: "warning", label: "Not started" },
  disabled: { tone: "neutral", label: "Disabled on this server" },
  unknown: { tone: "neutral", label: "Unknown" },
};

/** Settings → System status: backend, engine and broker health, platform controls, the audit log. */
export function SystemStatusPanel() {
  const { isAdmin } = useSession();
  const system = useApi<SystemStatus>("/system/status", undefined, 15_000);
  return (
    <div className="space-y-6">
      <HealthCard system={system.data} error={system.error} onRetry={() => void system.reload()} />
      <BrokerHealthCard />
      {isAdmin && <PlatformCard onChanged={() => void system.reload()} />}
      <AuditCard />
    </div>
  );
}

function Row({ label, children, detail }: { label: ReactNode; children: ReactNode; detail?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="min-w-0 text-sm text-fg sm:text-right">
        {children}
        {detail && (typeof detail === "string" && detail.length > 140 ? (
          // Long technical messages (engine errors) stay available but don't flood the card.
          <details className="mt-1 text-xs text-fg-muted">
            <summary className="cursor-pointer text-fg-subtle hover:text-fg">{detail.slice(0, 90).trimEnd()}… <span className="underline">Show details</span></summary>
            <span className="mt-1 block break-words font-mono text-[11px] leading-relaxed sm:text-left">{detail}</span>
          </details>
        ) : <span className="mt-0.5 block text-xs break-words text-fg-muted">{detail}</span>)}
      </dd>
    </div>
  );
}

function HealthCard({ system, error, onRetry }: { system: SystemStatus | null; error: string | null; onRetry: () => void }) {
  const { status } = useAppData();
  const trading = system?.trading ?? status;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Server className="size-4 text-fg-muted" aria-hidden /> System</CardTitle>
        <CardDescription>Health of the trading engine, the database and the server&apos;s safety settings. Refreshes every 15 seconds.</CardDescription>
      </CardHeader>
      <CardContent>
        {error && !system ? (
          <ErrorState message={error} onRetry={onRetry} />
        ) : !system || !trading ? (
          <ListSkeleton rows={4} />
        ) : (
          <div className="grid gap-x-10 md:grid-cols-2" aria-live="polite">
            <dl className="divide-y divide-border">
              {(() => {
                const view = engineHealthView({ ...trading, engine_summary: system.engine_summary ?? trading.engine_summary });
                return (
                  <Row label="Trading engine" detail={view.message}>
                    <Pill tone={view.tone} dot>{view.label}</Pill>
                  </Row>
                );
              })()}
              <Row label="Engine API service" detail={system.engine_service?.detail ?? undefined}>
                {system.engine_service ? (
                  system.engine_service.status === "online"
                    ? <Pill tone="positive">Online{system.engine_service.version ? ` · v${system.engine_service.version}` : ""}</Pill>
                    : system.engine_service.status === "error"
                      ? <Pill tone="negative">Answering with an error</Pill>
                      : <Pill tone="negative">Unreachable</Pill>
                ) : system.engine.status === "ok"
                  ? <Pill tone="positive">Reachable{system.engine.version ? ` · v${system.engine.version}` : ""}</Pill>
                  : <Pill tone="negative">Unreachable</Pill>}
              </Row>
              <Row label="Trading supervisor" detail={system.engine_supervisor?.detail ?? trading.engine_detail}>
                {system.engine_supervisor
                  ? <Pill tone={SUPERVISOR[system.engine_supervisor.state].tone} dot>{SUPERVISOR[system.engine_supervisor.state].label}</Pill>
                  : <Pill tone={ENGINE[trading.engine_state].tone} dot>{ENGINE[trading.engine_state].label}</Pill>}
              </Row>
              <Row label="Supervisor heartbeat" detail={trading.engine_heartbeat_at ? formatDateTime(trading.engine_heartbeat_at) : undefined}>
                <span className="num">{trading.engine_heartbeat_at ? formatRelative(trading.engine_heartbeat_at) : "Never"}</span>
              </Row>
              <Row label="Database">{system.database === "ok" ? <Pill tone="positive">OK</Pill> : <Pill tone="negative">Error</Pill>}</Row>
              <Row label="Background jobs queue"><span className="num">{system.queue_connection}</span></Row>
            </dl>
            <dl className="divide-y divide-border">
              <Row label="Platform" detail={trading.platform_halted ? trading.platform_halt_reason ?? undefined : undefined}>
                {trading.platform_halted ? <Pill tone="negative" dot>Halted by an administrator</Pill> : <Pill tone="positive">Normal</Pill>}
              </Row>
              <Row label="Real-money (LIVE) lock" detail={system.live_trading_enabled ? "Users may authorise LIVE trading." : "LIVE_TRADING_ENABLED=false — no real-money account can trade."}>
                {system.live_trading_enabled ? <Pill tone="live">Unlocked</Pill> : <Pill tone="positive">Locked</Pill>}
              </Row>
              <Row label="Deriv App ID">
                {system.deriv_app_id_configured ? <Pill tone="positive">Configured</Pill> : <Pill tone="warning">Missing (DERIV_APP_ID)</Pill>}
              </Row>
              <Row label="Broker credential vault">
                {system.broker_vault_configured ? <Pill tone="positive">Configured</Pill> : <Pill tone="negative">Not configured — run php artisan tp:keys</Pill>}
              </Row>
              <Row label="Two-factor required for everyone">{system.mfa_required ? "Yes" : "No"}</Row>
            </dl>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BrokerHealthCard() {
  const { accounts } = useAppData();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Cable className="size-4 text-fg-muted" aria-hidden /> Broker connections</CardTitle>
        <CardDescription>As reported by the trading engine for each of your accounts.</CardDescription>
      </CardHeader>
      <CardContent>
        {accounts === null ? (
          <ListSkeleton rows={2} />
        ) : accounts.length === 0 ? (
          <p className="text-sm text-fg-muted">No broker accounts yet. Add one in the Brokers tab.</p>
        ) : (
          <ul className="divide-y divide-border" aria-live="polite">
            {accounts.map((a) => (
              <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 py-2.5">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium text-fg"><span className="truncate">{a.label}</span> <EnvBadge env={a.environment} /></p>
                  <p className="text-xs text-fg-muted">
                    {a.broker}{a.connection_detail ? ` · ${a.connection_detail}` : ""}
                    {a.last_connected_at ? ` · last connected ${formatRelative(a.last_connected_at)}` : ""}
                  </p>
                </div>
                <ConnectionBadge status={a.connection_status} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Admins only: stop (or allow again) every user's trading at once. */
function PlatformCard({ onChanged }: { onChanged: () => void }) {
  const { status, reloadStatus } = useAppData();
  const [haltOpen, setHaltOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();

  const call = async (path: string, body: unknown, success: string) => {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST", body });
      toast.success(success);
      setHaltOpen(false);
      setResumeOpen(false);
      setReason("");
      await reloadStatus();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const halted = status?.platform_halted ?? false;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Activity className="size-4 text-fg-muted" aria-hidden /> Platform halt <Pill tone="info">Admin</Pill></CardTitle>
        <CardDescription>Stops new trades for every user at once. Each user&apos;s own Stop switch is not changed, and open positions are not closed.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!status ? (
          <ListSkeleton rows={1} />
        ) : halted ? (
          <>
            <Notice tone="danger" title="The platform is halted">{status.platform_halt_reason ?? "No reason given."}</Notice>
            <Button onClick={() => { setError(null); setResumeOpen(true); }}><Play aria-hidden /> Resume the platform…</Button>
          </>
        ) : (
          <Button variant="destructive" onClick={() => { setError(null); setHaltOpen(true); }}><OctagonPause aria-hidden /> Halt the platform…</Button>
        )}
      </CardContent>

      <AlertDialog open={haltOpen} onOpenChange={setHaltOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Halt trading for every user?</AlertDialogTitle>
            <AlertDialogDescription>No user can open a trade until an administrator resumes the platform. Everyone is notified with your reason.</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor={reasonId}>Reason (required)</Label>
            <Textarea id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} rows={3} />
          </div>
          {error && <p role="alert" className="text-sm text-negative">{error}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button variant="destructive" disabled={busy || !reason.trim()} onClick={() => void call("/admin/halt", { reason: reason.trim() }, "Platform halted")}>
              {busy ? "Halting…" : "Halt the platform"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ConfirmDialog open={resumeOpen} onOpenChange={setResumeOpen} title="Resume the platform?" confirmLabel="Resume" busy={busy} error={error}
        onConfirm={() => void call("/admin/resume", { confirm: true }, "Platform resumed")}>
        <p>Users can trade again. Each user&apos;s own Stop switch still applies, so nobody starts trading unless they had started.</p>
      </ConfirmDialog>
    </Card>
  );
}

// Success is the norm, so it stays neutral; only refusals and failures get a status colour.
const OUTCOME: Record<AuditEntry["outcome"], Tone> = { success: "neutral", denied: "warning", failure: "negative" };

function AuditCard() {
  const audit = useApi<Paginated<AuditEntry>>("/audit", { per_page: 100 });
  const rows = audit.data?.data ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ScrollText className="size-4 text-fg-muted" aria-hidden /> Audit log</CardTitle>
        <CardDescription>Every security and trading action, allowed or refused. It can&apos;t be changed or deleted.</CardDescription>
      </CardHeader>
      <CardContent>
        {audit.error && !rows ? (
          <ErrorState message={audit.error} onRetry={() => void audit.reload()} />
        ) : !rows ? (
          <ListSkeleton rows={5} />
        ) : rows.length === 0 ? (
          <EmptyState icon={ScrollText} title="Nothing recorded yet">Sign-ins, broker changes and trading controls will be listed here.</EmptyState>
        ) : (
          <>
            {/* Phones: cards */}
            <ul className="divide-y divide-border sm:hidden">
              {rows.map((r) => (
                <li key={r.id} className="space-y-1 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-fg">{describeAuditAction(r.action)}</p>
                    <Pill tone={OUTCOME[r.outcome]}>{r.outcome}</Pill>
                  </div>
                  <p className="text-xs text-fg-muted">{formatDateTime(r.occurred_at)} · {r.actor_label}</p>
                </li>
              ))}
            </ul>
            {/* Larger screens: table */}
            <div className="hidden sm:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Who</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead className="hidden lg:table-cell">IP</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="num text-xs text-fg-muted">{formatDateTime(r.occurred_at)}</TableCell>
                      <TableCell className="whitespace-normal">{describeAuditAction(r.action)}</TableCell>
                      <TableCell className="text-fg-muted">{r.actor_label}</TableCell>
                      <TableCell><Pill tone={OUTCOME[r.outcome]}>{r.outcome}</Pill></TableCell>
                      <TableCell className="num hidden text-xs text-fg-muted lg:table-cell">{r.ip_address ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
