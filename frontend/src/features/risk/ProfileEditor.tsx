"use client";

import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Select, TextInput, Toggle } from "@/components/ui/Fields";
import { Notice } from "@/components/ui/Misc";
import { apiRequest } from "@/lib/api";
import type { RiskLimits, RiskProfile } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";
import { LIMIT_GROUPS, SESSIONS } from "./limitsMeta";

type Draft = Record<string, string | string[]>;

function toDraft(limits: RiskLimits): Draft {
  const d: Draft = {};
  for (const [k, v] of Object.entries(limits)) d[k] = Array.isArray(v) ? v : v === null ? "" : String(v);
  return d;
}

function fromDraft(d: Draft): RiskLimits {
  const out: RiskLimits = {};
  for (const [k, v] of Object.entries(d)) out[k] = Array.isArray(v) ? v : v.trim() === "" ? null : v.trim();
  return out;
}

export function ProfileEditor() {
  const profiles = useApiResource<RiskProfile[]>("/risk/profiles");
  const [chosen, setSelected] = useState<string>("");
  const selected = chosen || profiles.data?.[0]?.id || "";
  const current = profiles.data?.find((p) => p.id === selected) ?? null;
  return (
    <Card>
      <CardHeader
        title="Risk profiles"
        description="Limits the risk engine enforces. An account uses exactly one profile; assign it on the Brokers page."
        action={
          <Select aria-label="Profile" value={selected} onChange={(e) => setSelected(e.target.value)} className="w-auto">
            {profiles.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        }
      />
      {current && (
        <ProfileForm
          key={`${current.id}:${current.updated_at}`}
          profile={current}
          onSaved={() => void profiles.reload()}
          onDuplicated={async (id) => {
            await profiles.reload();
            setSelected(id);
          }}
        />
      )}
    </Card>
  );
}

function ProfileForm({ profile, onSaved, onDuplicated }: { profile: RiskProfile; onSaved: () => void; onDuplicated: (id: string) => void }) {
  const { isOwner } = useSession();
  const [draft, setDraft] = useState<Draft>(() => toDraft(profile.limits));
  const [name, setName] = useState(profile.name);
  const [saved, setSaved] = useState(false);
  const action = useAction();
  const selected = profile.id;
  const current = profile;

  const save = async () => {
    setSaved(false);
    const res = await action.run(() =>
      apiRequest<RiskProfile>(`/risk/profiles/${selected}`, { method: "PUT", body: { name, limits: fromDraft(draft) } }),
    );
    if (res) {
      setSaved(true);
      onSaved();
    }
  };
  const duplicate = async () => {
    const res = await action.run(() =>
      apiRequest<RiskProfile>("/risk/profiles", { method: "POST", body: { name: `${name} (copy)`, limits: fromDraft(draft) } }),
    );
    if (res) onDuplicated(res.id);
  };

  return (
      <CardBody className="space-y-6">
        <Field label="Profile name">
          <TextInput value={name} disabled={!isOwner} onChange={(e) => setName(e.target.value)} />
        </Field>
        {LIMIT_GROUPS.map((group) => (
          <fieldset key={group.title}>
            <legend className="mb-3 text-xs font-medium tracking-wide text-fg-subtle uppercase">{group.title}</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {group.items.map((m) =>
                m.kind === "sessions" ? (
                  <div key={m.key} className="sm:col-span-2">
                    <p className="mb-2 text-xs font-medium text-fg-muted">{m.label}</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {SESSIONS.map((s) => {
                        const list = (draft[m.key] as string[] | undefined) ?? [];
                        return (
                          <Toggle key={s.key} checked={list.includes(s.key)} disabled={!isOwner} label={s.label}
                            onChange={(on) => setDraft((d) => ({ ...d, [m.key]: on ? [...list, s.key] : list.filter((x) => x !== s.key) }))} />
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <Field key={m.key} label={<>{m.label}{m.unit && <span className="text-fg-subtle"> ({m.unit})</span>}</>} hint={`${m.help}${m.optional ? " Leave empty for no limit." : ""}`}>
                    <TextInput inputMode="decimal" disabled={!isOwner} value={(draft[m.key] as string | undefined) ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [m.key]: e.target.value }))} />
                  </Field>
                ),
              )}
            </div>
          </fieldset>
        ))}
        <Notice tone="info">A stop loss on every trade is always mandatory and cannot be switched off.</Notice>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
        {saved && <Notice tone="success">Saved. The change is recorded in the audit log and applies to the next signal.</Notice>}
        {isOwner && (
          <div className="flex justify-end gap-2">
            <Button variant="ghost" disabled={action.busy} onClick={() => void duplicate()}>Duplicate</Button>
            <Button variant="primary" disabled={action.busy || !current} onClick={() => void save()}>Save profile</Button>
          </div>
        )}
      </CardBody>
  );
}
