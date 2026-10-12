"use client";

import { Check, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/app/states";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { AdminUser } from "@/lib/types";

type Pending = { user: AdminUser; action: "approve" | "disable" | "enable" } | null;

const VERB = { approve: "Approve", disable: "Disable", enable: "Enable" } as const;

/** Settings → Users (admins only): approve new sign-ups, disable or re-enable accounts. */
export function UsersPanel() {
  const { user: me } = useSession();
  const users = useApi<{ users: AdminUser[] }>("/admin/users", undefined, 30_000);
  const [pending, setPending] = useState<Pending>(null);
  const action = useAction();
  const list = users.data?.users ?? [];
  const waiting = list.filter((u) => !u.approved).length;

  const confirm = async () => {
    if (!pending) return;
    const res = await action.run(() => api<AdminUser>(`/admin/users/${pending.user.id}/${pending.action}`, { method: "POST" }));
    if (res) {
      toast.success(`${res.name}: ${pending.action === "approve" ? "approved" : pending.action === "disable" ? "disabled" : "enabled"}`);
      setPending(null);
      void users.reload();
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl font-extrabold">Users</CardTitle>
        <CardDescription>
          New sign-ups wait here until you approve them. {waiting > 0 ? `${waiting} waiting.` : "Nobody is waiting."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {users.error ? (
          <ErrorState message={users.error} onRetry={() => void users.reload()} />
        ) : !users.data ? (
          <ListSkeleton />
        ) : list.length === 0 ? (
          <EmptyState icon={UserCheck} title="No users yet" className="py-6" />
        ) : (
          <ul className="-mx-2 divide-y divide-line">
            {list.map((u) => (
              <li key={u.id} className="flex flex-wrap items-center gap-3 p-2 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-bold text-fg">{u.name}</span>
                    {!u.approved && <Pill tone="warning" dot>Waiting</Pill>}
                    {!u.is_active && <Pill tone="negative">Disabled</Pill>}
                    {u.role === "admin" && <Pill tone="info">Admin</Pill>}
                  </p>
                  <p className="truncate text-[13px] text-fg-muted">{u.email}</p>
                  <p className="text-xs text-fg-subtle">
                    Signed up {formatRelative(u.created_at)}
                    {u.last_login_at ? ` · last sign-in ${formatRelative(u.last_login_at)}` : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  {!u.approved && (
                    <Button size="sm" onClick={() => setPending({ user: u, action: "approve" })}><Check aria-hidden /> Approve</Button>
                  )}
                  {u.id !== me.id && (u.is_active
                    ? <Button size="sm" variant="outline" onClick={() => setPending({ user: u, action: "disable" })}><UserX aria-hidden /> Disable</Button>
                    : <Button size="sm" variant="outline" onClick={() => setPending({ user: u, action: "enable" })}><UserCheck aria-hidden /> Enable</Button>)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => { if (!open) { setPending(null); action.reset(); } }}
        title={pending ? `${VERB[pending.action]} ${pending.user.name}?` : ""}
        confirmLabel={pending ? VERB[pending.action] : ""}
        onConfirm={() => void confirm()}
        busy={action.busy}
        error={action.error}
        destructive={pending?.action === "disable"}
      >
        {pending?.action === "approve" && <p>{pending.user.email} will be able to use 2kPilot. Their trading starts stopped, in demo mode.</p>}
        {pending?.action === "disable" && <p>{pending.user.email} is signed out everywhere and can&apos;t sign in. Nothing is deleted; you can enable the account again.</p>}
        {pending?.action === "enable" && <p>{pending.user.email} will be able to sign in again.</p>}
      </ConfirmDialog>
    </Card>
  );
}
