"use client";

import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { PriceField, RulesCatalog } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type OperandKind, type OperandState, defaultParams, findIndicator } from "./model";

const KIND_LABEL: Record<OperandKind, string> = {
  price: "Price",
  value: "Number",
  indicator: "Indicator",
};

/** One side of a condition: a price field, a number, or an indicator with its settings. */
export function OperandPicker({
  catalog,
  value,
  onChange,
  label,
  invalid,
  kinds = ["price", "value", "indicator"],
}: {
  catalog: RulesCatalog;
  value: OperandState;
  onChange: (next: OperandState) => void;
  /** "Left side", "Right side", "Low", "High" — prefixes every control's accessible name. */
  label: string;
  invalid?: boolean;
  kinds?: OperandKind[];
}) {
  const uid = useId();
  const spec = value.kind === "indicator" ? findIndicator(catalog, value.indicator) : undefined;

  const setIndicator = (key: string) => {
    const next = findIndicator(catalog, key);
    onChange({ ...value, indicator: key, params: defaultParams(next), output: next?.default_output ?? "value" });
  };

  return (
    <div className="grid min-w-0 grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
      <div className={cn("flex min-w-0 flex-col gap-1", value.kind === "indicator" && "max-sm:col-span-2")}>
        <span className="text-xs text-fg-subtle" aria-hidden>
          {label}
        </span>
        <Select value={value.kind} onValueChange={(k) => onChange({ ...value, kind: k as OperandKind })}>
          <SelectTrigger size="sm" aria-label={`${label}: type`} className="w-30 max-sm:w-full" aria-invalid={invalid || undefined}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {kinds.map((k) => (
              <SelectItem key={k} value={k}>
                {KIND_LABEL[k]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {value.kind === "price" && (
        <Select value={value.price} onValueChange={(p) => onChange({ ...value, price: p as PriceField })}>
          <SelectTrigger size="sm" aria-label={`${label}: price`} className="w-28 max-sm:w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {catalog.price_fields.map((p) => (
              <SelectItem key={p.key} value={p.key}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {value.kind === "value" && (
        <Input
          type="number"
          inputMode="decimal"
          step="any"
          aria-label={`${label}: number`}
          aria-invalid={invalid || undefined}
          className="h-7 w-28 max-sm:w-full"
          value={value.value}
          onChange={(e) => onChange({ ...value, value: e.target.value })}
        />
      )}

      {value.kind === "indicator" && (
        <>
          <Select value={value.indicator} onValueChange={setIndicator}>
            <SelectTrigger size="sm" aria-label={`${label}: indicator`} className="max-w-full min-w-36 max-sm:col-span-2 max-sm:w-full max-sm:min-w-0">
              <SelectValue placeholder="Choose an indicator" />
            </SelectTrigger>
            <SelectContent>
              {catalog.indicators.map((i) => (
                <SelectItem key={i.key} value={i.key}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {spec?.params.map((p) => {
            const id = `${uid}-${p.key}`;
            const current = value.params[p.key] ?? String(p.default);
            const setParam = (v: string) => onChange({ ...value, params: { ...value.params, [p.key]: v } });
            return (
              <div key={p.key} className="flex min-w-0 flex-col gap-1">
                <label htmlFor={id} className="truncate text-xs text-fg-subtle">
                  {p.label}
                </label>
                {p.type === "source" ? (
                  <Select value={current} onValueChange={setParam}>
                    <SelectTrigger id={id} size="sm" className="w-24 max-sm:w-full" aria-label={`${label}: ${spec.short} ${p.label.toLowerCase()}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(p.options ?? catalog.price_fields.map((f) => f.key)).map((o) => (
                        <SelectItem key={o} value={o}>
                          {catalog.price_fields.find((f) => f.key === o)?.label ?? o}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id={id}
                    type="number"
                    inputMode={p.type === "integer" ? "numeric" : "decimal"}
                    step={p.type === "integer" ? 1 : "any"}
                    min={p.min ?? undefined}
                    max={p.max ?? undefined}
                    title={p.description || undefined}
                    aria-label={`${label}: ${spec.short} ${p.label.toLowerCase()}`}
                    aria-invalid={invalid || undefined}
                    className={cn("h-7 max-sm:w-full", p.type === "integer" ? "w-20" : "w-24")}
                    value={current}
                    onChange={(e) => setParam(e.target.value)}
                  />
                )}
              </div>
            );
          })}

          {spec && spec.outputs.length > 1 && (
            <div className="flex min-w-0 flex-col gap-1">
              <label htmlFor={`${uid}-output`} className="text-xs text-fg-subtle">
                Line
              </label>
              <Select value={value.output || spec.default_output} onValueChange={(o) => onChange({ ...value, output: o })}>
                <SelectTrigger id={`${uid}-output`} size="sm" className="max-w-full min-w-32 max-sm:w-full max-sm:min-w-0" aria-label={`${label}: ${spec.short} line`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {spec.outputs.map((o) => (
                    <SelectItem key={o.key} value={o.key}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {spec && (
            <details className="w-full text-xs text-fg-muted max-sm:col-span-2">
              <summary className="w-fit cursor-pointer text-fg-subtle hover:text-fg max-sm:py-2">What is {spec.short}?</summary>
              <p className="mt-1 max-w-prose leading-relaxed">{spec.description}</p>
              {spec.notes.map((n) => (
                <p key={n} className="mt-1 max-w-prose leading-relaxed">
                  {n}
                </p>
              ))}
            </details>
          )}
        </>
      )}
    </div>
  );
}
