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
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/model", label: "Модель", icon: Cpu },
  { href: "/gpu", label: "GPU", icon: Gauge },
  { href: "/system", label: "Система", icon: Server },
  { href: "/cost", label: "Стоимость", icon: DollarSign },
  { href: "/logs", label: "Логи", icon: ScrollText },
  { href: "/alerts", label: "Алерты", icon: Bell },
  { href: "/health", label: "Health", icon: HeartPulse },
];

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

/** Вертикальная колонка иконок-закладок (Настройки — внизу). */
export function Sidebar() {
  return (
    <aside className="fixed left-3 top-16 bottom-4 z-20 flex w-14 flex-col items-center gap-1 rounded-2xl border border-line bg-panel py-3">
      <nav className="relative flex flex-col gap-1">
        {NAV.map((item) => (
          <NavItem key={item.href} {...item} />
        ))}
      </nav>
      <div className="mt-auto flex flex-col items-center gap-1">
        <NavItem href="/settings" label="Настройки" icon={Settings} />
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
  );
}
