"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, TextInput } from "@/components/ui/Fields";
import { Notice } from "@/components/ui/Misc";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAction } from "@/lib/hooks";
import type { RiskProfile } from "@/lib/types";

type Limit = { key: keyof RiskProfile; label: string; unit: string; help: string; required?: boolean };

/** Every limit, grouped and explained. Empty = this optional limit is off. */
export const LIMIT_GROUPS: { title: string; limits: Limit[] }[] = [
  { title: "Per trade", limits: [
    { key: "risk_per_trade_pct", label: "Risk per trade", unit: "% of equity", help: "Money lost if the stop loss is hit. Position size is calculated from this.", required: true },
    { key: "max_position_lots", label: "Maximum position size", unit: "lots", help: "Upper cap per position, whatever the sizing says." },
    { key: "min_stop_pips", label: "Minimum stop distance", unit: "pips", help: "Stops closer than this are too easily hit by noise." },
    { key: "max_stop_pips", label: "Maximum stop distance", unit: "pips", help: "Very wide stops mean very small positions." },
    { key: "min_reward_risk", label: "Minimum reward:risk", unit: "× risk", help: "e.g. 1.5 = the target must be at least 1.5 times the stop distance." },
  ] },
  { title: "Loss limits", limits: [
    { key: "max_daily_loss_pct", label: "Daily loss limit", unit: "%", help: "New trades stop for the day once losses (closed + open) reach this." },
    { key: "max_weekly_loss_pct", label: "Weekly loss limit", unit: "%", help: "Same for the week (Monday 00:00 UTC)." },
    { key: "max_drawdown_pct", label: "Maximum drawdown", unit: "% from peak", help: "Hitting this switches trading off for the account until you review it." },
    { key: "cooldown_after_losses", label: "Pause after losing streak", unit: "losses in a row", help: "Consecutive-loss cooldown: start a pause after this many losses…" },
    { key: "cooldown_minutes", label: "Pause length", unit: "minutes", help: "…for this long." },
  ] },
  { title: "Exposure", limits: [
    { key: "max_open_positions", label: "Maximum open positions", unit: "positions", help: "Across all symbols on the account." },
    { key: "max_positions_per_symbol", label: "Positions per symbol", unit: "positions", help: "Avoid stacking trades on one instrument." },
    { key: "max_symbol_exposure_lots", label: "Symbol exposure", unit: "lots", help: "Total size open on one symbol." },
    { key: "max_total_exposure_lots", label: "Account exposure", unit: "lots", help: "Total size open on the whole account." },
    { key: "max_total_risk_pct", label: "Total open risk", unit: "% of equity", help: "Sum of the risk of all open positions." },
    { key: "max_trades_per_day", label: "Maximum trades per day", unit: "trades", help: "Prevents over-trading." },
  ] },
  { title: "Market conditions", limits: [
    { key: "max_spread_pips", label: "Spread protection", unit: "pips", help: "Skip trades when the spread is wider than this." },
    { key: "max_slippage_pips", label: "Slippage protection", unit: "pips", help: "Maximum price deviation accepted when the order fills." },
    { key: "max_data_age_seconds", label: "Maximum price age", unit: "seconds", help: "Never trade on a stale price.", required: true },
  ] },
];

const SESSIONS = ["ASIA", "LONDON", "OVERLAP", "NEW_YORK"] as const;

export function ProfileEditor({ profile, open, onClose, onSaved }: { profile: RiskProfile | null; open: boolean; onClose: () => void; onSaved: () => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => toForm(profile));
  const [sessions, setSessions] = useState<string[]>(profile?.allowed_sessions ?? ["LONDON", "OVERLAP", "NEW_YORK"]);
  const [name, setName] = useState(profile?.name ?? "");
  const action = useAction();
  const save = async () => {
    const body: Record<string, unknown> = { name, allowed_sessions: sessions, trading_hours_start: values.trading_hours_start || null, trading_hours_end: values.trading_hours_end || null };
    for (const group of LIMIT_GROUPS) for (const l of group.limits) body[l.key] = values[l.key] === "" || values[l.key] === undefined ? null : Number(values[l.key]);
    const ok = await action.run(() => profile ? api(`/risk/profiles/${profile.id}`, { method: "PUT", body }) : api("/risk/profiles", { method: "POST", body }));
    if (ok !== null) onSaved();
  };
  const err = (k: string) => action.fieldErrors[k]?.[0] ?? null;
  return (
    <Dialog open={open} onClose={onClose} size="xl" title={profile ? `Edit ${profile.name}` : "New risk profile"}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={action.busy || !name} onClick={() => void save()}>Save profile</Button></>}>
      <div className="space-y-6">
        <Field label="Name" error={err("name")}><TextInput value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <p className="text-sm text-fg-muted">Leave a field empty to switch that limit off. The stop-loss requirement, STOP TRADING and the LIVE lock always apply and cannot be switched off.</p>
        {LIMIT_GROUPS.map((group) => (
          <section key={group.title}>
            <h3 className="mb-3 text-sm font-semibold text-fg">{group.title}</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {group.limits.map((l) => (
                <Field key={l.key} label={`${l.label} (${l.unit})${l.required ? " *" : ""}`} hint={l.help} error={err(l.key)}>
                  <TextInput inputMode="decimal" className="num" value={values[l.key] ?? ""} onChange={(e) => setValues({ ...values, [l.key]: e.target.value })} placeholder={l.required ? "required" : "off"} />
                </Field>
              ))}
            </div>
          </section>
        ))}
        <section>
          <h3 className="mb-3 text-sm font-semibold text-fg">Trading hours</h3>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Allowed sessions">
            {SESSIONS.map((s) => (
              <button key={s} type="button" aria-pressed={sessions.includes(s)} onClick={() => setSessions(sessions.includes(s) ? sessions.filter((x) => x !== s) : [...sessions, s])}
                className={cn("rounded-full border px-3 py-1 text-sm", sessions.includes(s) ? "border-accent bg-accent/10 text-fg" : "border-line text-fg-muted")}>
                {s.replace("_", " ").toLowerCase()}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-fg-subtle">Market sessions the robot may trade in (none selected = any session).</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Only trade from (UTC)" hint="Optional window, e.g. 07:00" error={err("trading_hours_start")}><TextInput type="time" value={values.trading_hours_start ?? ""} onChange={(e) => setValues({ ...values, trading_hours_start: e.target.value })} /></Field>
            <Field label="Until (UTC)" error={err("trading_hours_end")}><TextInput type="time" value={values.trading_hours_end ?? ""} onChange={(e) => setValues({ ...values, trading_hours_end: e.target.value })} /></Field>
          </div>
        </section>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}

function toForm(profile: RiskProfile | null): Record<string, string> {
  const defaults: Record<string, string> = { risk_per_trade_pct: "0.5", max_daily_loss_pct: "2", max_weekly_loss_pct: "4", max_drawdown_pct: "10", max_open_positions: "3", max_data_age_seconds: "120", min_stop_pips: "8", max_stop_pips: "150", min_reward_risk: "1.5", max_spread_pips: "2.5" };
  if (!profile) return defaults;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(profile)) if (typeof v === "string" || typeof v === "number") out[k] = String(Number.isNaN(Number(v)) ? v : Number(v));
  out.trading_hours_start = profile.trading_hours_start ?? "";
  out.trading_hours_end = profile.trading_hours_end ?? "";
  return out;
}
