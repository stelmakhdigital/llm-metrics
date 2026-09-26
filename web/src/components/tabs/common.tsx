"use client";

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** KPI-карточка: подпись, значение, опциональная подстрока/дочерний контент. */
export function KpiCard({
  label,
  value,
  sub,
  children,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-line bg-panel p-3", className)}>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 truncate text-lg font-semibold leading-6">{value}</div>
      {sub != null && sub !== "" && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
      {children}
    </div>
  );
}

/** Лейблы серий с цветными точками (легенда над графиком). */
export function LegendChips({
  items,
}: {
  items: { name: string; color: string }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
      {items.map((it) => (
        <span key={it.name} className="flex items-center gap-1 text-xs text-muted">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: it.color }}
          />
          {it.name}
        </span>
      ))}
    </div>
  );
}

/** Карточка-график: заголовок, легенда, содержимое. */
export function ChartCard({
  title,
  legend,
  note,
  children,
  className,
}: {
  title: string;
  legend?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-line bg-panel p-3", className)}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-1">
        <div className="text-sm font-medium">{title}</div>
        {legend}
      </div>
      {children}
      {note != null && note !== "" && <div className="mt-1 text-xs text-muted">{note}</div>}
    </div>
  );
}

/** Баннер ошибки API. */
export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
      Ошибка API: {message}
    </div>
  );
}

/** Информационный баннер (offline-источник и т.п.). */
export function InfoBanner({ message }: { message: string }) {
  return (
    <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
      {message}
    </div>
  );
}

/** «Нет данных» внутри карточки-графика. */
export function NoData({ text = "Нет данных" }: { text?: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-muted">{text}</div>
  );
}

/** Skeleton KPI-карточки. */
export function SkeletonKpi({ rows = 8 }: { rows?: number }) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-[72px] animate-pulse rounded-xl border border-line bg-panel2" />
      ))}
    </div>
  );
}

/** Skeleton блока-графика. */
export function SkeletonChart({ height = 220 }: { height?: number }) {
  return (
    <div className="animate-pulse rounded-xl border border-line bg-panel p-3">
      <div className="mb-2 h-4 w-32 animate-pulse rounded bg-panel2" />
      <div className="w-full animate-pulse rounded bg-panel2" style={{ height }} />
    </div>
  );
}
