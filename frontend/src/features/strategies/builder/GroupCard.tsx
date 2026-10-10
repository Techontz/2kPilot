"use client";

import { Plus } from "lucide-react";
import { type ReactNode, useId } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { RulesCatalog } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ConditionRow } from "./ConditionRow";
import { type ConditionState, type GroupMode, type GroupState, cloneCondition, defaultCondition } from "./model";

/** A list of conditions edited in place (used by groups and the filters list). */
export function ConditionList({
  catalog,
  conditions,
  onChange,
  canAdd,
  problemsFor,
  addLabel = "Add a condition",
  newCondition,
}: {
  catalog: RulesCatalog;
  conditions: ConditionState[];
  onChange: (next: ConditionState[]) => void;
  canAdd: boolean;
  problemsFor: (id: string) => string[];
  addLabel?: string;
  newCondition?: () => ConditionState;
}) {
  const update = (i: number, c: ConditionState) => onChange(conditions.map((x, j) => (j === i ? c : x)));
  return (
    <div className="flex flex-col gap-3">
      {conditions.map((c, i) => (
        <ConditionRow
          key={c.id}
          catalog={catalog}
          index={i}
          value={c}
          onChange={(next) => update(i, next)}
          onRemove={() => onChange(conditions.filter((_, j) => j !== i))}
          onDuplicate={() => onChange([...conditions.slice(0, i + 1), cloneCondition(c), ...conditions.slice(i + 1)])}
          canDuplicate={canAdd}
          problems={problemsFor(c.id)}
        />
      ))}
      <div>
        <Button type="button" variant="outline" size="sm" disabled={!canAdd} onClick={() => onChange([...conditions, newCondition ? newCondition() : defaultCondition(catalog)])}>
          <Plus aria-hidden /> {addLabel}
        </Button>
      </div>
    </div>
  );
}

/** A switchable group: "Buy (go up) when…" with All/Any and its condition list. */
export function GroupCard({
  catalog,
  title,
  hint,
  switchLabel,
  group,
  onToggle,
  onChange,
  canAdd,
  problemsFor,
  groupProblems,
  newCondition,
  footer,
}: {
  catalog: RulesCatalog;
  title: string;
  hint?: ReactNode;
  switchLabel: string;
  group: GroupState | null;
  onToggle: (on: boolean) => void;
  onChange: (next: GroupState) => void;
  canAdd: boolean;
  problemsFor: (id: string) => string[];
  groupProblems: string[];
  newCondition?: () => ConditionState;
  footer?: ReactNode;
}) {
  const uid = useId();
  const on = group !== null;
  return (
    <section aria-labelledby={`${uid}-title`} className={cn("min-w-0 rounded-xl border border-line bg-card p-4", !on && "bg-surface-raised/40")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={`${uid}-title`} className="font-semibold text-fg">
            {title}
          </h3>
          {hint && <p className="mt-0.5 text-sm text-fg-muted">{hint}</p>}
        </div>
        <label className="flex items-center gap-2 text-sm text-fg-muted">
          <Switch checked={on} onCheckedChange={onToggle} aria-label={switchLabel} />
          <span aria-hidden>{on ? "On" : "Off"}</span>
        </label>
      </div>

      {group && (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={`${uid}-mode`} className="text-sm text-fg-muted">
              Match
            </label>
            <Select value={group.mode} onValueChange={(m) => onChange({ ...group, mode: m as GroupMode })}>
              <SelectTrigger id={`${uid}-mode`} size="sm" className="max-w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {catalog.groups.map((g) => (
                  <SelectItem key={g.key} value={g.key}>
                    {g.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <ConditionList
            catalog={catalog}
            conditions={group.conditions}
            onChange={(conditions) => onChange({ ...group, conditions })}
            canAdd={canAdd}
            problemsFor={problemsFor}
            newCondition={newCondition}
          />
          {groupProblems.length > 0 && (
            <ul className="space-y-0.5 text-sm text-negative" role="status">
              {groupProblems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {footer}
        </div>
      )}
    </section>
  );
}
