"use client";

import { Copy, Trash2 } from "lucide-react";
import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { OperatorKey, RulesCatalog } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ConditionState, isCross } from "./model";
import { OperandPicker } from "./OperandPicker";

/** "Buy rule, condition 2 (left side): EMA period …" → "Left side: EMA period …" (the row already says where). */
export function shortProblem(text: string): string {
  const m = /^(?:Buy rule|Sell rule|Exit rule for buys|Exit rule for sells|Filter \d+)(?:, condition \d+)?(?: \((\w+) side\))?: (.*)$/.exec(text);
  if (!m) return text;
  const [, side, rest = text] = m;
  return side ? `${side.charAt(0).toUpperCase()}${side.slice(1)} side: ${rest}` : rest;
}

/** One condition: left operand → operator → right operand (or low & high), optional "within N bars". */
export function ConditionRow({
  catalog,
  index,
  value,
  onChange,
  onRemove,
  onDuplicate,
  canDuplicate,
  problems,
}: {
  catalog: RulesCatalog;
  index: number;
  value: ConditionState;
  onChange: (next: ConditionState) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  canDuplicate: boolean;
  problems: string[];
}) {
  const uid = useId();
  const errorId = `${uid}-errors`;
  const invalid = problems.length > 0;
  const operator = catalog.operators.find((o) => o.key === value.op);
  const supportsWithin = operator?.supports_within_bars ?? isCross(value.op);
  const withinOn = value.withinBars.trim() !== "";
  const maxWithin = catalog.limits.max_within_bars;

  const setOp = (op: OperatorKey) => onChange({ ...value, op, withinBars: isCross(op) ? value.withinBars : "" });

  return (
    <fieldset
      aria-describedby={invalid ? errorId : undefined}
      aria-invalid={invalid || undefined}
      className={cn("min-w-0 rounded-lg border border-line bg-surface p-3 sm:p-4", invalid && "border-negative/50")}
    >
      <legend className="sr-only">Condition {index + 1}</legend>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-semibold text-fg-muted" aria-hidden>
          <span className="num flex size-5 items-center justify-center rounded-full bg-muted text-[11px] font-bold text-fg">{index + 1}</span>
          Condition {index + 1}
        </span>
        <div className="flex items-center gap-1">
          <Button type="button" variant="ghost" size="icon-sm" onClick={onDuplicate} disabled={!canDuplicate} aria-label={`Duplicate condition ${index + 1}`} title="Duplicate">
            <Copy aria-hidden />
          </Button>
          <Button type="button" variant="ghost" size="icon-sm" onClick={onRemove} aria-label={`Remove condition ${index + 1}`} title="Remove">
            <Trash2 aria-hidden />
          </Button>
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-3 xl:flex-row xl:flex-wrap xl:items-end">
        <OperandPicker catalog={catalog} label="Left side" value={value.left} onChange={(left) => onChange({ ...value, left })} invalid={invalid} />

        <div className="flex flex-col gap-1">
          <label htmlFor={`${uid}-op`} className="text-xs text-fg-subtle">
            Test
          </label>
          <Select value={value.op} onValueChange={(op) => setOp(op as OperatorKey)}>
            <SelectTrigger id={`${uid}-op`} size="sm" className="w-full sm:w-40" aria-label="Test">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {catalog.operators.map((o) => (
                <SelectItem key={o.key} value={o.key}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {value.op === "between" ? (
          <>
            <OperandPicker catalog={catalog} label="Low" value={value.low} onChange={(low) => onChange({ ...value, low })} invalid={invalid} />
            <span className="text-sm text-fg-muted xl:pb-1.5" aria-hidden>
              and
            </span>
            <OperandPicker catalog={catalog} label="High" value={value.high} onChange={(high) => onChange({ ...value, high })} invalid={invalid} />
          </>
        ) : (
          <OperandPicker catalog={catalog} label="Right side" value={value.right} onChange={(right) => onChange({ ...value, right })} invalid={invalid} />
        )}
      </div>

      {operator?.description && <p className="mt-2 text-xs text-fg-subtle">{operator.description}</p>}

      {supportsWithin && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-2 text-fg-muted">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={withinOn}
              onChange={(e) => onChange({ ...value, withinBars: e.target.checked ? "3" : "" })}
            />
            The cross may have happened within the last
          </label>
          {withinOn && (
            <>
              <Input
                type="number"
                inputMode="numeric"
                min={1}
                max={maxWithin}
                step={1}
                aria-label="Number of bars"
                className="h-7 w-16"
                value={value.withinBars}
                onChange={(e) => onChange({ ...value, withinBars: e.target.value })}
              />
              <span className="text-fg-muted">bars (1–{maxWithin})</span>
            </>
          )}
        </div>
      )}

      {invalid && (
        <ul id={errorId} className="mt-2 space-y-0.5 text-sm text-negative">
          {problems.map((p) => (
            <li key={p}>{shortProblem(p)}</li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
