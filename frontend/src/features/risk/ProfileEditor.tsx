"use client";

import { useId, useState } from "react";
import { toast } from "sonner";
import { Notice } from "@/components/app/states";
import { Term } from "@/components/app/term";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { RiskProfile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ADVANCED_GROUPS, advancedErrorKeys, BASIC_FIELDS, type LimitField, SESSIONS, toBody, toForm, unitLabel } from "./riskForm";

const ADVANCED = "advanced";

/** Create or edit a risk profile. Beginner (stake) limits first; Spot limits tucked away. */
export function ProfileEditor({
  profile,
  open,
  currency,
  onClose,
  onSaved,
}: {
  profile: RiskProfile | null;
  open: boolean;
  currency?: string | null;
  onClose: () => void;
  onSaved: (profile: RiskProfile) => void;
}) {
  const [form, setForm] = useState(() => toForm(profile));
  const [advancedOpen, setAdvancedOpen] = useState<string>("");
  const action = useAction();
  const nameId = useId();

  const err = (key: string) => action.fieldErrors[key]?.[0] ?? null;
  const setValue = (key: string, value: string) => setForm((f) => ({ ...f, values: { ...f.values, [key]: value } }));

  const save = async () => {
    const body = toBody(form);
    const result = await action.run(() =>
      profile
        ? api<RiskProfile>(`/risk/profiles/${profile.id}`, { method: "PUT", body })
        : api<RiskProfile>("/risk/profiles", { method: "POST", body }),
    );
    if (result) {
      toast.success(profile ? "Risk profile saved" : "Risk profile created");
      onSaved(result);
    }
  };

  const errors = action.fieldErrors;
  const hiddenErrors = advancedOpen !== ADVANCED && advancedErrorKeys(errors).length > 0;

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-xl">
        <SheetHeader className="border-b border-line">
          <SheetTitle>{profile ? `Edit ${profile.name}` : "New risk profile"}</SheetTitle>
          <SheetDescription>Leave a limit empty to switch it off. STOP TRADING and the real-money lock always apply.</SheetDescription>
        </SheetHeader>
        <form
          id="risk-profile-form"
          className="flex-1 space-y-6 overflow-y-auto p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor={nameId}>Name</Label>
            <Input id={nameId} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={120} required
              aria-invalid={Boolean(err("name"))} />
            {err("name") && <p role="alert" className="text-sm text-negative">{err("name")}</p>}
          </div>

          <section className="space-y-4">
            <h3 className="text-sm font-semibold text-fg">Everyday limits</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {BASIC_FIELDS.map((f) => (
                <LimitInput key={f.key} field={f} currency={currency} value={form.values[f.key] ?? ""} error={err(f.key)} onChange={(v) => setValue(f.key, v)} />
              ))}
            </div>
          </section>

          {hiddenErrors && <Notice tone="danger">Some advanced limits need fixing — open “Advanced (Spot trading on Paper)” below.</Notice>}

          <Accordion type="single" collapsible value={advancedOpen} onValueChange={setAdvancedOpen}>
            <AccordionItem value={ADVANCED} className="rounded-lg border border-line px-3">
              <AccordionTrigger>Advanced (Spot trading on Paper)</AccordionTrigger>
              <AccordionContent className="space-y-6 pb-4">
                <p className="text-sm text-fg-muted">These apply to Spot trades (lots and pips) on Paper accounts. Contract trades on Deriv use the everyday limits above.</p>
                {ADVANCED_GROUPS.map((g) => (
                  <section key={g.title} className="space-y-3">
                    <h4 className="text-sm font-medium text-fg">{g.title}</h4>
                    <div className="grid gap-4 sm:grid-cols-2">
                      {g.fields.map((f) => (
                        <LimitInput key={f.key} field={f} currency={currency} value={form.values[f.key] ?? ""} error={err(f.key)} onChange={(v) => setValue(f.key, v)} />
                      ))}
                    </div>
                  </section>
                ))}
                <section className="space-y-3">
                  <h4 className="text-sm font-medium text-fg">Trading hours</h4>
                  <div className="flex flex-wrap gap-2" role="group" aria-label="Allowed sessions">
                    {SESSIONS.map((s) => {
                      const on = form.sessions.includes(s);
                      return (
                        <button
                          key={s}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setForm({ ...form, sessions: on ? form.sessions.filter((x) => x !== s) : [...form.sessions, s] })}
                          className={cn("rounded-full border px-3 py-1 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                            on ? "border-primary bg-primary/10 text-fg" : "border-line text-fg-muted hover:bg-muted/50")}
                        >
                          {s.replace("_", " ").toLowerCase()}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-xs text-fg-muted">Market sessions the robot may trade in (none selected = any session).</p>
                  {err("allowed_sessions") && <p role="alert" className="text-sm text-negative">{err("allowed_sessions")}</p>}
                  <div className="grid gap-4 sm:grid-cols-2">
                    <TimeInput label="Only trade from (UTC)" value={form.hoursStart} error={err("trading_hours_start")} onChange={(v) => setForm({ ...form, hoursStart: v })} />
                    <TimeInput label="Until (UTC)" value={form.hoursEnd} error={err("trading_hours_end")} onChange={(v) => setForm({ ...form, hoursEnd: v })} />
                  </div>
                </section>
              </AccordionContent>
            </AccordionItem>
          </Accordion>

          {action.error && Object.keys(errors).length === 0 && <Notice tone="danger">{action.error}</Notice>}
        </form>
        <SheetFooter className="flex-row justify-end border-t border-line">
          <Button variant="ghost" onClick={onClose} disabled={action.busy}>Cancel</Button>
          <Button type="submit" form="risk-profile-form" disabled={action.busy || !form.name.trim()}>
            {action.busy ? "Saving…" : "Save profile"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function LimitInput({ field, currency, value, error, onChange }: { field: LimitField; currency?: string | null; value: string; error: string | null; onChange: (v: string) => void }) {
  const id = useId();
  const unit = unitLabel(field.unit, currency);
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <Label htmlFor={id} className="flex-wrap gap-1">
          {field.label}
          {unit && <span className="font-normal text-fg-muted">({unit})</span>}
          {field.required && <span className="text-negative" aria-hidden>*</span>}
        </Label>
        {field.term && <span className="text-xs text-fg-muted"><Term id={field.term}>What&apos;s this?</Term></span>}
      </div>
      <Input
        id={id}
        inputMode={field.unit === "count" || field.unit === "minutes" || field.unit === "seconds" ? "numeric" : "decimal"}
        className="num"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.required ? "required" : "off"}
        required={field.required}
        aria-invalid={Boolean(error)}
        aria-describedby={`${id}-help${error ? ` ${id}-err` : ""}`}
      />
      <p id={`${id}-help`} className="text-xs text-fg-muted">{field.help}</p>
      {error && <p id={`${id}-err`} role="alert" className="text-sm text-negative">{error}</p>}
    </div>
  );
}

function TimeInput({ label, value, error, onChange }: { label: string; value: string; error: string | null; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="time" value={value} onChange={(e) => onChange(e.target.value)} aria-invalid={Boolean(error)} />
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
    </div>
  );
}
