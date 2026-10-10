import { History, House, type LucideIcon, Settings, SlidersHorizontal } from "lucide-react";

export interface NavItem {
  href: "/" | "/strategies" | "/history" | "/settings";
  label: string;
  icon: LucideIcon;
}

/** Exactly four sections — everything else lives inside one of them (as a tab). */
export const NAVIGATION: readonly NavItem[] = [
  { href: "/", label: "Home", icon: House },
  { href: "/strategies", label: "Strategies", icon: SlidersHorizontal },
  { href: "/history", label: "History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
