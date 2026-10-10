"use client";

import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FAMILY_LABEL } from "@/lib/contracts";
import type { ContractFamily, RulesCatalog } from "@/lib/types";
import { STOP_BOUNDS, type StopState, TARGET_BOUNDS, type TargetState } from "./model";
import { contractExitText } from "./preview";

const FAMILIES: ContractFamily[] = ["RISE_FALL", "MULTIPLIER", "SPOT"];

/** How exits work for each contract family (from the catalogue). */
export function ContractExitNotes({ catalog }: { catalog: RulesCatalog }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-3">
      {FAMILIES.map((f) => (
        <div key={f} className="rounded-lg border border-line bg-surface-raised/50 p-3 text-sm">
          <dt className="font-medium text-fg">{FAMILY_LABEL[f]}</dt>
          <dd className="mt-0.5 text-fg-muted">{contractExitText(f, catalog)}</dd>
        </div>
      ))}
    </dl>
  );
}

type Bounds = { min: number; max: number; integer: boolean; exclusiveMin?: boolean };

function NumberField({
  label,
  value,
  onChange,
  bounds,
  hint,
  invalid,
  describedBy,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  bounds: Bounds;
  hint: string;
  invalid: boolean;
  describedBy?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-fg-subtle">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        inputMode={bounds.integer ? "numeric" : "decimal"}
        step={bounds.integer ? 1 : "any"}
        min={bounds.exclusiveMin ? undefined : bounds.min}
        max={bounds.max}
        className="h-8 w-28"
        value={value}
        aria-invalid={invalid || undefined}
        aria-describedby={[`${id}-hint`, describedBy].filter(Boolean).join(" ")}
        onChange={(e) => onChange(e.target.value)}
      />
      <span id={`${id}-hint`} className="text-xs text-fg-subtle">
        {hint}
      </span>
    </div>
  );
}

/** Stop and target (Spot and Multiplier trades). */
export function StopTargetEditor({
  catalog,
  stop,
  target,
  onStop,
  onTarget,
  stopProblems,
  targetProblems,
}: {
  catalog: RulesCatalog;
  stop: StopState;
  target: TargetState;
  onStop: (s: StopState) => void;
  onTarget: (t: TargetState) => void;
  stopProblems: string[];
  targetProblems: string[];
}) {
  const uid = useId();
  const stopErr = `${uid}-stop-err`;
  const targetErr = `${uid}-target-err`;
  const sBad = stopProblems.length > 0;
  const tBad = targetProblems.length > 0;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="min-w-0 rounded-lg border border-line bg-surface p-3">
        <label htmlFor={`${uid}-stop`} className="text-sm font-medium text-fg">
          Stop
        </label>
        <p className="text-xs text-fg-muted">Where a losing trade is closed, measured from the entry.</p>
        <Select value={stop.type} onValueChange={(t) => onStop({ ...stop, type: t as StopState["type"] })}>
          <SelectTrigger id={`${uid}-stop`} size="sm" className="mt-2 max-w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {catalog.stop_types.map((t) => (
              <SelectItem key={t.key} value={t.key}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="mt-3 flex flex-wrap gap-3">
          {stop.type === "pips" ? (
            <NumberField label="Pips" value={stop.pips} onChange={(pips) => onStop({ ...stop, pips })} bounds={STOP_BOUNDS.pips} hint="More than 0" invalid={sBad} describedBy={sBad ? stopErr : undefined} />
          ) : (
            <>
              <NumberField label="Multiple of ATR" value={stop.multiple} onChange={(multiple) => onStop({ ...stop, multiple })} bounds={STOP_BOUNDS.multiple} hint="0.1–20" invalid={sBad} describedBy={sBad ? stopErr : undefined} />
              <NumberField label="ATR period" value={stop.atr_period} onChange={(atr_period) => onStop({ ...stop, atr_period })} bounds={STOP_BOUNDS.atr_period} hint="1–500 bars" invalid={sBad} describedBy={sBad ? stopErr : undefined} />
            </>
          )}
        </div>
        {sBad && (
          <ul id={stopErr} className="mt-2 space-y-0.5 text-sm text-negative">
            {stopProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="min-w-0 rounded-lg border border-line bg-surface p-3">
        <label htmlFor={`${uid}-target`} className="text-sm font-medium text-fg">
          Target
        </label>
        <p className="text-xs text-fg-muted">Where a winning trade is closed.</p>
        <Select value={target.type} onValueChange={(t) => onTarget({ ...target, type: t as TargetState["type"] })}>
          <SelectTrigger id={`${uid}-target`} size="sm" className="mt-2 max-w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {catalog.target_types.map((t) => (
              <SelectItem key={t.key} value={t.key}>
                {t.label}
              </SelectItem>
            ))}
            <SelectItem value="none">No target</SelectItem>
          </SelectContent>
        </Select>
        <div className="mt-3 flex flex-wrap gap-3">
          {target.type === "rr" && (
            <NumberField label="Times the stop distance" value={target.ratio} onChange={(ratio) => onTarget({ ...target, ratio })} bounds={TARGET_BOUNDS.ratio} hint="0.1–20 (2 = twice the risk)" invalid={tBad} describedBy={tBad ? targetErr : undefined} />
          )}
          {target.type === "atr" && (
            <>
              <NumberField label="Multiple of ATR" value={target.multiple} onChange={(multiple) => onTarget({ ...target, multiple })} bounds={TARGET_BOUNDS.multiple} hint="0.1–50" invalid={tBad} describedBy={tBad ? targetErr : undefined} />
              <NumberField label="ATR period" value={target.atr_period} onChange={(atr_period) => onTarget({ ...target, atr_period })} bounds={TARGET_BOUNDS.atr_period} hint="1–500 bars" invalid={tBad} describedBy={tBad ? targetErr : undefined} />
            </>
          )}
          {target.type === "pips" && (
            <NumberField label="Pips" value={target.pips} onChange={(pips) => onTarget({ ...target, pips })} bounds={TARGET_BOUNDS.pips} hint="More than 0" invalid={tBad} describedBy={tBad ? targetErr : undefined} />
          )}
          {target.type === "none" && (
            <p className="text-sm text-fg-muted">Without a target, Spot trades are refused when your risk profile requires a minimum reward/risk.</p>
          )}
        </div>
        {tBad && (
          <ul id={targetErr} className="mt-2 space-y-0.5 text-sm text-negative">
            {targetProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
