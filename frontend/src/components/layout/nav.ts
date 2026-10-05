import {
  BarChart3,
  Bell,
  BookOpen,
  Cable,
  CandlestickChart,
  FlaskConical,
  History,
  LayoutDashboard,
  ListOrdered,
  type LucideIcon,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  SquarePen,
  Wallet,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** The order the user asked for, in four light groups. */
export const NAVIGATION: { title: string; items: NavItem[] }[] = [
  {
    title: "Trading",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/markets", label: "Markets", icon: CandlestickChart },
      { href: "/trade", label: "Trade", icon: SquarePen },
      { href: "/strategies", label: "Strategies", icon: SlidersHorizontal },
      { href: "/backtesting", label: "Backtesting", icon: FlaskConical },
    ],
  },
  {
    title: "Activity",
    items: [
      { href: "/positions", label: "Positions", icon: Wallet },
      { href: "/orders", label: "Orders", icon: ListOrdered },
      { href: "/history", label: "History", icon: History },
    ],
  },
  {
    title: "Accounts",
    items: [
      { href: "/brokers", label: "Brokers", icon: Cable },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/risk", label: "Risk", icon: ShieldCheck },
      { href: "/journal", label: "Journal", icon: BookOpen },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/notifications", label: "Notifications", icon: Bell },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
