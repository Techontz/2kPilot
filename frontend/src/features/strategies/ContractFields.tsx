"use client";

import { useId } from "react";
import { Term } from "@/components/app/term";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { availableFamilies, DURATION_UNITS, FAMILY_HELP, FAMILY_LABEL, rangesText, specForFamily } from "@/lib/contracts";
import type { ContractFamily, ContractOffer, ContractSpec, DurationUnit } from "@/lib/types";
import { cn } from "@/lib/utils";

const COMMON_MULTIPLIERS = [10, 20, 50, 100, 200];

export type ContractErrors = Partial<Record<keyof ContractSpec, string>>;

/**
 * "How should each trade work?" — contract family, then its settings, with
 * the allowed ranges from the broker's offer (GET /api/markets/contracts).
 * The stake is handled by the caller (it comes from the risk profile).
 */
export function ContractFields({ spec, onChange, offer, isDeriv, errors = {}, families: only }: {
  spec: ContractSpec;
  onChange: (spec: ContractSpec) => void;
  offer?: ContractOffer | null;
  isDeriv: boolean;
  errors?: ContractErrors;
  families?: ContractFamily[];
}) {
  const id = useId();
  const families = only ?? availableFamilies(offer, isDeriv);
  const ranges = offer?.families.RISE_FALL.durations ?? [];
  const multipliers = offer?.families.MULTIPLIER.multipliers.length ? offer.families.MULTIPLIER.multipliers : COMMON_MULTIPLIERS;
  const err = (key: keyof ContractSpec) => errors[key] ? <p id={`${id}-${key}-err`} className="text-xs text-negative">{errors[key]}</p> : null;

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-fg">Contract type</legend>
        {families.length === 0 && <p className="text-sm text-negative">This market offers no contract 2kPilot can trade.</p>}
        <RadioGroup value={spec.contract_family} onValueChange={(v) => onChange(specForFamily(v as ContractFamily, { ...spec, stake: spec.stake }))} className="grid gap-2 sm:grid-cols-3">
          {families.map((f) => (
            <Label key={f} htmlFor={`${id}-${f}`}
              className={cn("flex cursor-pointer flex-col items-start gap-1 rounded-lg border p-3 font-normal", spec.contract_family === f ? "border-primary bg-primary/5" : "border-line hover:border-line-strong")}>
              <span className="flex items-center gap-2 text-sm font-medium text-fg">
                <RadioGroupItem id={`${id}-${f}`} value={f} />
                {f === "RISE_FALL" ? <Term id="riseFall" /> : f === "MULTIPLIER" ? <Term id="multiplier" /> : FAMILY_LABEL[f]}
              </span>
              <span className="text-xs leading-snug text-fg-muted">{f === "RISE_FALL" ? "Up or down over a fixed time" : f === "MULTIPLIER" ? "Profit/loss × a multiplier" : "Paper only, in lots"}</span>
            </Label>
          ))}
        </RadioGroup>
        {err("contract_family")}
        <p className="text-xs text-fg-subtle">{FAMILY_HELP[spec.contract_family]}</p>
      </fieldset>

      {spec.contract_family === "RISE_FALL" && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-duration`}>Lasts for</Label>
              <Input id={`${id}-duration`} type="number" inputMode="numeric" min={1} step={1} className="num"
                value={spec.duration ?? ""} aria-invalid={Boolean(errors.duration)} aria-describedby={errors.duration ? `${id}-duration-err` : `${id}-duration-help`}
                onChange={(e) => onChange({ ...spec, duration: e.target.value === "" ? null : Number(e.target.value) })} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-unit`}>Unit</Label>
              <Select value={spec.duration_unit ?? "m"} onValueChange={(v) => onChange({ ...spec, duration_unit: v as DurationUnit })}>
                <SelectTrigger id={`${id}-unit`} className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{DURATION_UNITS.map((u) => <SelectItem key={u.value} value={u.value}>{u.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          {err("duration")}
          <p id={`${id}-duration-help`} className="text-xs text-fg-subtle">
            It settles automatically at <Term id="expiry">expiry</Term> and can&apos;t be closed early.
            {ranges.length > 0 && <> Allowed here: {rangesText(ranges)}.</>}
            {" "}Strategies decide on closed candles, so a duration of a few candles works best.
          </p>
          {offer?.families.RISE_FALL.allow_equals && (
            <Label className="flex items-center gap-2 font-normal">
              <Checkbox checked={spec.allow_equals} onCheckedChange={(v) => onChange({ ...spec, allow_equals: v === true })} />
              Also win when the price ends exactly where it started (lower payout)
            </Label>
          )}
          {err("allow_equals")}
        </div>
      )}

      {spec.contract_family === "MULTIPLIER" && (
        <div className="space-y-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-mult`}>Multiplier</Label>
            <Select value={spec.multiplier ? String(spec.multiplier) : ""} onValueChange={(v) => onChange({ ...spec, multiplier: Number(v) })}>
              <SelectTrigger id={`${id}-mult`} className="w-full sm:w-48" aria-invalid={Boolean(errors.multiplier)}><SelectValue placeholder="Choose…" /></SelectTrigger>
              <SelectContent>{multipliers.map((m) => <SelectItem key={m} value={String(m)}>×{m}</SelectItem>)}</SelectContent>
            </Select>
            {err("multiplier")}
            <p className="text-xs text-fg-subtle">Higher multipliers move faster both ways. You can never lose more than the stake.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["take_profit_amount", "stop_loss_amount"] as const).map((key) => (
              <div key={key} className="grid gap-1.5">
                <Label htmlFor={`${id}-${key}`}>{key === "take_profit_amount" ? "Take profit at (optional)" : "Stop loss at (optional)"}</Label>
                <Input id={`${id}-${key}`} type="number" inputMode="decimal" min={0} step="0.01" className="num" placeholder="From the strategy"
                  value={spec[key] ?? ""} aria-invalid={Boolean(errors[key])}
                  onChange={(e) => onChange({ ...spec, [key]: e.target.value === "" ? null : e.target.value })} />
                {err(key)}
              </div>
            ))}
          </div>
          <p className="text-xs text-fg-subtle">Money amounts. Leave them empty to use the strategy&apos;s own stop and target.</p>
        </div>
      )}

      {spec.contract_family === "SPOT" && (
        <p className="text-sm text-fg-muted">Each trade is a position in lots with the strategy&apos;s stop loss and target, sized so that hitting the stop loses your <em>risk per trade</em>.</p>
      )}
    </div>
  );
}
