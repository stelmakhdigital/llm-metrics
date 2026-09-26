"use client";

import { cn } from "@/lib/utils";

/** Канонические уровни (api/app/logs/parse.py). */
export const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
export type LogLevel = (typeof LOG_LEVELS)[number];

/** Цветные чипы уровней (ТЗ §5.6): INFO серый/синий, WARNING жёлтый,
 * ERROR красный, DEBUG тусклый. */
export const LEVEL_CHIP_STYLES: Record<string, string> = {
  INFO: "border-sky-500/30 bg-sky-500/10 text-sky-400",
  WARNING: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  ERROR: "border-red-500/30 bg-red-500/10 text-red-400",
  CRITICAL: "border-red-600/50 bg-red-600/20 text-red-300",
  DEBUG: "border-line bg-panel2 text-muted",
};

/** Цвета сегментов мини-графика «логи по уровням». */
export const LEVEL_BAR_COLORS: Record<string, string> = {
  DEBUG: "#4b5563",
  INFO: "#38bdf8",
  WARNING: "#facc15",
  ERROR: "#ef4444",
  CRITICAL: "#b91c1c",
};

/** Компактный цветной чип уровня. */
export function LevelChip({ level, className }: { level: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-block shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold leading-4",
        LEVEL_CHIP_STYLES[level] ?? LEVEL_CHIP_STYLES.INFO,
        className,
      )}
    >
      {level}
    </span>
  );
}
