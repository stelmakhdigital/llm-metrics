"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Cpu,
  Gauge,
  Server,
  DollarSign,
  ScrollText,
  Settings,
  Bell,
  HeartPulse,
  LayoutDashboard,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/overview", label: "Сводка", icon: LayoutDashboard },
  { href: "/model", label: "Модель", icon: Cpu },
  { href: "/gpu", label: "GPU", icon: Gauge },
  { href: "/system", label: "Система", icon: Server },
  { href: "/cost", label: "Цена", icon: DollarSign },
  { href: "/logs", label: "Логи", icon: ScrollText },
  { href: "/alerts", label: "Алерты", icon: Bell },
  { href: "/health", label: "Health", icon: HeartPulse },
];
const SETTINGS: (typeof NAV)[number] = { href: "/settings", label: "Настр.", icon: Settings };
const ALL_NAV = [...NAV, SETTINGS];

function NavItem({ href, label, icon: Icon }: (typeof NAV)[number]) {
  const active = usePathname() === href;
  return (
    <Link
      href={href}
      title={label}
      className={cn(
        "flex size-10 items-center justify-center rounded-lg transition-colors",
        active
          ? "bg-accent/15 text-accent"
          : "text-muted hover:bg-panel2 hover:text-foreground",
      )}
    >
      <Icon className="size-5" />
      {active && (
        <span className="absolute -left-2.5 h-4 w-0.5 rounded-full bg-accent" aria-hidden />
      )}
    </Link>
  );
}

/** Мобильный пункт нижней панели: touch-target ≥ 40px (M5). */
function NavItemMobile({ href, label, icon: Icon }: (typeof NAV)[number]) {
  const active = usePathname() === href;
  return (
    <Link
      href={href}
      aria-label={label}
      className={cn(
        "flex min-h-12 min-w-10 flex-1 flex-col items-center justify-center gap-0.5 py-1",
        active ? "text-accent" : "text-muted",
      )}
    >
      <Icon className="size-5" />
      <span className="text-[10px] leading-none">{label}</span>
    </Link>
  );
}

/** Навигация: ≥md — левая колонка иконок; <md — нижняя горизонтальная панель. */
export function Sidebar() {
  return (
    <>
      {/* Desktop (≥md) */}
      <aside className="fixed left-3 top-16 bottom-4 z-20 hidden w-14 flex-col items-center gap-1 rounded-2xl border border-line bg-panel py-3 md:flex">
        <nav className="relative flex flex-col gap-1">
          {NAV.map((item) => (
            <NavItem key={item.href} {...item} />
          ))}
        </nav>
        <div className="mt-auto flex flex-col items-center gap-1">
          <NavItem {...SETTINGS} />
          {process.env.NEXT_PUBLIC_APP_VERSION && (
            <span
              title={`версия ${process.env.NEXT_PUBLIC_APP_VERSION}`}
              className="select-none text-[10px] leading-none text-muted/70 tabular-nums"
            >
              v{process.env.NEXT_PUBLIC_APP_VERSION}
            </span>
          )}
        </div>
      </aside>

      {/* Mobile (<md): нижняя панель навигации */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden">
        {ALL_NAV.map((item) => (
          <NavItemMobile key={item.href} {...item} />
        ))}
      </nav>
    </>
  );
}
