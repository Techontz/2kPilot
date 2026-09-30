"use client";

import { Select } from "@/components/ui/Fields";
import type { TradingAccount } from "@/lib/types";

interface AccountPickerProps {
  accounts: TradingAccount[];
  value: string | null;
  onChange: (id: string | null) => void;
  allowAll?: boolean;
}

export function AccountPicker({ accounts, value, onChange, allowAll = false }: AccountPickerProps) {
  return (
    <Select
      aria-label="Account"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-auto min-w-48"
    >
      {allowAll && <option value="">All accounts</option>}
      {accounts.map((a) => (
        <option key={a.id} value={a.id}>
          {a.label} · {a.environment}
        </option>
      ))}
    </Select>
  );
}
