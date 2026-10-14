"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api";
import type { Strategy, StrategyVersion } from "@/lib/types";
import { buildParameters, changedKeys, initialValues, type ParamField, paramFields } from "./paramForm";

/**
 * Edit a built-in (code) strategy's settings. Saving makes a new version; the
 * markets it's active on move to it and keep trading, so the change applies
 * from the next candle.
 */
export function ParametersDialog({ strategy, open, onOpenChange, onSaved }: { strategy: Strategy; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const fields = paramFields(strategy);
  const [values, setValues] = useState(() => initialValues(strategy, fields));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const active = strategy.assignments.filter((a) => a.status === "ENABLED");

  const save = async () => {
    const built = buildParameters(strategy, fields, values);
    setErrors(built.errors);
    if (Object.keys(built.errors).length) return;
    const changed = changedKeys(strategy, built.parameters);
    if (changed.length === 0) {
      onOpenChange(false);
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      const version = await api<StrategyVersion>(`/strategies/${strategy.id}/versions`, {
        method: "POST",
        body: { parameters: built.parameters, notes: `Changed: ${changed.join(", ")}` },
      });
      // Switching pauses a market (a new configuration is enabled deliberately); this save is that decision.
      for (const a of active) {
        await api(`/assignments/${a.id}/version`, { method: "PUT", body: { strategy_version_id: version.id } });
        await api(`/assignments/${a.id}/enable`, { method: "POST" });
      }
      toast.success(`${strategy.name}: saved as version ${version.version}`, {
        description: active.length ? `Now used on ${active.map((a) => a.symbol).join(", ")} from the next candle.` : "Activate it on a market to use it.",
      });
      onOpenChange(false);
      onSaved();
    } catch (e) {
      setFailure(e instanceof ApiError || e instanceof Error ? e.message : "Saving failed.");
      onSaved(); // show whatever did change (e.g. a market left paused)
    } finally {
      setBusy(false);
    }
  };

  const groups: { id: ParamField["group"]; title: string; note: string }[] = [
    { id: "trading", title: "How much and how often it trades", note: "Caps here can only make your risk profile stricter, never looser." },
    { id: "signal", title: "Signal details", note: "Advanced: how the strategy reads the market. Test on history after changing these." },
  ];

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{strategy.name} settings</DialogTitle>
          <DialogDescription>
            Saving creates a new version.{active.length > 0 && ` It replaces the current one on ${active.map((a) => a.symbol).join(", ")} and keeps trading.`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-8">
          {groups.map((g) => {
            const list = fields.filter((f) => f.group === g.id);
            if (list.length === 0) return null;
            return (
              <section key={g.id} className="space-y-4">
                <div>
                  <h3 className="font-bold text-fg">{g.title}</h3>
                  <p className="text-sm text-fg-muted">{g.note}</p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {list.map((f) => (
                    <FieldInput key={f.key} field={f} value={values[f.key] ?? ""} error={errors[f.key]}
                      onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: v }))} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
        {failure && <p role="alert" className="text-sm text-negative">{failure}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={() => void save()} disabled={busy}>{busy ? "Saving…" : "Save settings"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FieldInput({ field: f, value, error, onChange }: { field: ParamField; value: string; error?: string; onChange: (v: string) => void }) {
  const id = `param-${f.key}`;
  const range = f.min !== undefined && f.max !== undefined ? `${f.min}–${f.max}` : null;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{f.label}</Label>
      {f.kind === "choice" ? (
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger id={id} className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>{f.options?.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
        </Select>
      ) : f.kind === "toggle" ? (
        <Switch id={id} checked={value === "true"} onCheckedChange={(c) => onChange(String(c))} />
      ) : (
        <Input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={error ? true : undefined}
          aria-describedby={`${id}-help`} />
      )}
      <p id={`${id}-help`} className={error ? "text-xs text-negative" : "text-xs text-fg-subtle"}>
        {error ?? [f.help, range && `Allowed: ${range}.`].filter(Boolean).join(" ")}
      </p>
    </div>
  );
}
