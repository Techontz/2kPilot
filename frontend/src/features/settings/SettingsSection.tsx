"use client";

import { SectionTabs } from "@/components/layout/SectionTabs";
import { BrokersScreen } from "@/features/brokers/BrokersScreen";
import { RiskScreen } from "@/features/risk/RiskScreen";
import { NotificationsScreen } from "@/features/system/NotificationsScreen";
import { SecurityPanel } from "@/features/system/SecurityPanel";
import { SystemStatusPanel } from "@/features/system/SystemStatusPanel";
import { AccountsPanel } from "./AccountsPanel";

export const SETTINGS_TABS = ["brokers", "accounts", "risk", "notifications", "security", "system"] as const;

export function SettingsSection() {
  return (
    <SectionTabs
      title="Settings"
      description="Brokers and accounts, risk limits, notifications, security and system health."
      tabs={[
        { value: "brokers", label: "Brokers", content: <BrokersScreen /> },
        { value: "accounts", label: "Accounts", content: <AccountsPanel /> },
        { value: "risk", label: "Risk limits", content: <RiskScreen /> },
        { value: "notifications", label: "Notifications", content: <NotificationsScreen /> },
        { value: "security", label: "Security", content: <SecurityPanel /> },
        { value: "system", label: "System status", content: <SystemStatusPanel /> },
      ]}
    />
  );
}
