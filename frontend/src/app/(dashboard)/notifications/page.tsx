import type { Metadata } from "next";
import { NotificationsScreen } from "@/features/notifications/NotificationsScreen";

export const metadata: Metadata = { title: "Notifications" };

export default function Page() {
  return <NotificationsScreen />;
}
