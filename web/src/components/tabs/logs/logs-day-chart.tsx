"use client";

import type { LogDayStat } from "@/lib/api";
import { fmtDayShort } from "@/lib/format";
import { cn } from "@/lib/utils";
import { LEVEL_BAR_COLORS, LEVEL_CHIP_STYLES, LOG_LEVELS } from "./level";

/** Порядок сегментов stacked-бара (сверху вниз). */
const SEGMENT_ORDER: readonly string[] = [
  "CRITICAL",
  "ERROR",
  "WARNING",
  "INFO",
  "DEBUG",
];

/**
 * Мини-график «логи по уровням» за 7 дней: stacked-bar (INFO/WARN/ERROR/...),
 * клик по дню → выбор дня в фильтре; над баром — счётчик ошибок дня.
 * Данные — GET /api/logs/stats?from=now-7d (by_day).
 */
export function LogsDayChart({
  byDay,
  selectedDay,
  onSelectDay,
}: {
  byDay: LogDayStat[];
  /** epoch-с локальной полуночи выбранного дня */
  selectedDay: number;
  onSelectDay: (day: number) => void;
}) {
  const max = Math.max(1, ...byDay.map((d) => d.total));
  return (
    <div>
      <div className="flex h-36 items-stretch gap-2">
        {byDay.map((d) => {
          const errs = (d.levels.ERROR ?? 0) + (d.levels.CRITICAL ?? 0);
          const selected = d.day === selectedDay;
          const hPct = d.total > 0 ? Math.max(3, (d.total / max) * 100) : 0;
          return (
            <button
              key={d.day}
              type="button"
              onClick={() => onSelectDay(d.day)}
              title={`${fmtDayShort(d.day)}: ${d.total} строк, ошибок ${errs}`}
              className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1 rounded-md px-1 pb-1 pt-2 hover:bg-panel2/60"
            >
              <div className="relative flex w-full flex-1 items-end">
                {errs > 0 && (
                  <span className="absolute left-1/2 top-0 -translate-x-1/2 rounded bg-red-500/15 px-1 text-[10px] font-semibold tabular-nums text-red-400">
                    {errs}
                  </span>
                )}
                <div
                  className={cn(
                    "flex w-8 flex-col-reverse overflow-hidden rounded-t",
                    selected && "ring-1 ring-accent",
                  )}
                  style={{ height: `${hPct}%` }}
                >
                  {hPct === 0 && <div className="w-full bg-line" style={{ height: 3 }} />}
                  {hPct > 0 &&
                    SEGMENT_ORDER.map((lvl) => {
                      const n = d.levels[lvl] ?? 0;
                      if (n === 0) return null;
                      return (
                        <div
                          key={lvl}
                          style={{
                            height: `${(n / d.total) * 100}%`,
                            backgroundColor: LEVEL_BAR_COLORS[lvl],
                          }}
                        />
                      );
                    })}
                </div>
              </div>
              <div
                className={cn(
                  "text-[10px] tabular-nums",
                  selected ? "font-semibold text-accent" : "text-muted",
                )}
              >
                {fmtDayShort(d.day)}
              </div>
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
        {LOG_LEVELS.map((lvl) => (
          <span key={lvl} className="flex items-center gap-1 text-[10px] text-muted">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ backgroundColor: LEVEL_BAR_COLORS[lvl] }}
            />
            <span className={cn("rounded border px-1", LEVEL_CHIP_STYLES[lvl])}>{lvl}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
