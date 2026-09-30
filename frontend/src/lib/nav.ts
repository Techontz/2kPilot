import {
  Activity,
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
  ShieldAlert,
  SlidersHorizontal,
  Wallet,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

// Grouped by the question the user is asking: watching, building, or controlling.
export const NAVIGATION: NavGroup[] = [
  {
    title: "Monitor",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/positions", label: "Positions", icon: Wallet },
      { href: "/orders", label: "Orders", icon: ListOrdered },
      { href: "/history", label: "Trade History", icon: History },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/journal", label: "Journal", icon: BookOpen },
    ],
  },
  {
    title: "Research",
    items: [
      { href: "/markets", label: "Markets", icon: CandlestickChart },
      { href: "/strategies", label: "Strategies", icon: SlidersHorizontal },
      { href: "/backtesting", label: "Backtesting", icon: FlaskConical },
    ],
  },
  {
    title: "Control",
    items: [
      { href: "/trading", label: "Trading", icon: Activity },
      { href: "/risk", label: "Risk Management", icon: ShieldAlert },
      { href: "/brokers", label: "Brokers", icon: Cable },
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
