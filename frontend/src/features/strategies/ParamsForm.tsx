"use client";

import { Field, Select, TextInput, Toggle } from "@/components/ui/Fields";
import type { JsonSchemaProperty, StrategyInfo } from "@/lib/types";

export type ParamValues = Record<string, unknown>;

function enumFor(prop: JsonSchemaProperty, schema: StrategyInfo["parameter_schema"]): string[] | null {
  if (prop.enum) return prop.enum;
  const ref = prop.$ref ?? prop.allOf?.[0]?.$ref;
  if (ref) {
    const name = ref.split("/").pop() ?? "";
    return schema.$defs?.[name]?.enum ?? null;
  }
  return null;
}

function humanLabel(key: string, prop: JsonSchemaProperty) {
  return prop.title ?? key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
}

/** Renders a form for any strategy from its Pydantic JSON schema. */
export function ParamsForm({ schema, values, onChange, disabled }: {
  schema: StrategyInfo["parameter_schema"];
  values: ParamValues;
  onChange: (next: ParamValues) => void;
  disabled?: boolean;
}) {
  const set = (key: string, value: unknown) => onChange({ ...values, [key]: value });
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Object.entries(schema.properties).map(([key, prop]) => {
        const options = enumFor(prop, schema);
        const label = humanLabel(key, prop);
        const value = values[key];
        if (prop.type === "boolean") {
          return (
            <div key={key} className="sm:col-span-2">
              <Toggle checked={Boolean(value)} disabled={disabled} onChange={(v) => set(key, v)} label={label} description={prop.description} />
            </div>
          );
        }
        if (options) {
          return (
            <Field key={key} label={label} hint={prop.description}>
              <Select value={String(value ?? "")} disabled={disabled} onChange={(e) => set(key, e.target.value)}>
                {options.map((o) => <option key={o} value={o}>{o}</option>)}
              </Select>
            </Field>
          );
        }
        const numeric = prop.type === "integer" || prop.type === "number";
        const range = numeric && (prop.minimum !== undefined || prop.maximum !== undefined) ? ` Range ${prop.minimum ?? "…"}–${prop.maximum ?? "…"}.` : "";
        return (
          <Field key={key} label={label} hint={`${prop.description ?? ""}${range}`.trim() || undefined}>
            <TextInput
              inputMode={numeric ? "decimal" : undefined}
              disabled={disabled}
              value={value === undefined || value === null ? "" : String(value)}
              onChange={(e) => {
                const raw = e.target.value;
                set(key, numeric && raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw);
              }}
            />
          </Field>
        );
      })}
    </div>
  );
}
