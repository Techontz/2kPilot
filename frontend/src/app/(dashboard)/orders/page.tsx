import type { Metadata } from "next";
import { OrdersScreen } from "@/features/records/OrdersScreen";

export const metadata: Metadata = { title: "Orders" };

export default function Page() {
  return <OrdersScreen />;
}
