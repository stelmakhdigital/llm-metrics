"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Cpu,
  Gauge,
  Server,
  DollarSign,
  ScrollText,
  NotebookPen,
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
  { href: "/note", label: "Note", icon: NotebookPen },
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

/** Мобильный пункт нижней панели: touch-target ≥ 40px (M5). В компактном
 * режиме (>8 пунктов) — иконка без подписи: 10 × 40px держат target ≥ 40px
 * по обеим осям без truncate-деградации; панель прокручивается по X
 * (градиентная маска справа — аффордансность прокрутки). */
function NavItemMobile({
  href,
  label,
  icon: Icon,
  compact = false,
}: (typeof NAV)[number] & { compact?: boolean }) {
  const active = usePathname() === href;
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      className={cn(
        compact
          ? "flex min-w-10 min-h-12 shrink-0 items-center justify-center"
          : "flex min-h-12 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-0.5 py-1",
        active ? "text-accent" : "text-muted",
      )}
    >
      <Icon className="size-5 shrink-0" />
      {!compact && <span className="max-w-full truncate text-[10px] leading-none">{label}</span>}
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

      {/* Mobile (<md): нижняя панель навигации; >8 пунктов — компактные
          иконки без подписей + горизонтальная прокрутка с аффордансностью */}
      <nav className="fixed inset-x-0 bottom-0 z-30 flex items-stretch overflow-x-auto border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden">
        {ALL_NAV.map((item) => (
          <NavItemMobile key={item.href} compact={ALL_NAV.length > 8} {...item} />
        ))}
        {ALL_NAV.length > 8 && (
          <span
            aria-hidden
            className="pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-panel to-transparent"
          />
        )}
      </nav>
    </>
  );
}
