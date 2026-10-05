"use client";

import { Field, Select, TextInput, Toggle } from "@/components/ui/Fields";
import { humanize } from "@/lib/format";
import type { JsonSchemaProperty, Strategy } from "@/lib/types";

type Schema = NonNullable<Strategy["parameter_schema"]>;

function enumOf(prop: JsonSchemaProperty, schema: Schema): string[] | null {
  if (prop.enum) return prop.enum;
  const ref = prop.$ref ?? prop.allOf?.[0]?.$ref;
  if (!ref) return null;
  const def = schema.$defs?.[ref.split("/").pop() ?? ""];
  return def?.enum ?? null;
}

/** A form generated from the strategy's parameter schema (owned by the trading engine). */
export function ParamsEditor({ schema, value, onChange }: { schema: Schema; value: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Object.entries(schema.properties).map(([name, prop]) => {
        const current = value[name] ?? prop.default;
        const options = enumOf(prop, schema);
        const label = prop.title ?? humanize(name);
        if (prop.type === "boolean") {
          return (
            <div key={name} className="sm:col-span-2">
              <Toggle checked={Boolean(current)} onChange={(v) => onChange({ ...value, [name]: v })} label={label} description={prop.description} />
            </div>
          );
        }
        return (
          <Field key={name} label={label} hint={[prop.description, prop.minimum !== undefined ? `min ${prop.minimum}` : null, prop.maximum !== undefined ? `max ${prop.maximum}` : null].filter(Boolean).join(" · ")}>
            {options ? (
              <Select value={String(current ?? "")} onChange={(e) => onChange({ ...value, [name]: e.target.value })}>
                {options.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
              </Select>
            ) : (
              <TextInput inputMode="decimal" className="num" value={current === undefined || current === null ? "" : String(current)}
                onChange={(e) => onChange({ ...value, [name]: e.target.value === "" ? null : prop.type === "integer" ? parseInt(e.target.value, 10) : Number(e.target.value) })} />
            )}
          </Field>
        );
      })}
    </div>
  );
}
