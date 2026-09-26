"use client";

import { useState } from "react";
import {
  LOGS_SOURCES_URL,
  logsStatsUrl,
  usePoll,
  type LogSourcesData,
  type LogsStatsData,
} from "@/lib/api";
import { fmtDayFull, startOfDaySec } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ErrorBanner, InfoBanner } from "@/components/tabs/common";
import { LogsDayChart } from "@/components/tabs/logs/logs-day-chart";
import { LogsHistory } from "@/components/tabs/logs/logs-history";
import { LogsLive } from "@/components/tabs/logs/logs-live";

type LogsMode = "history" | "live";

const DAY_S = 86400;
/** Окно мини-графика «по дням», дней (ТЗ §5.6: 7 дней). */
const CHART_DAYS = 7;

function ModeToggle({ mode, onChange }: { mode: LogsMode; onChange: (m: LogsMode) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-line bg-panel p-0.5">
      {(
        [
          ["history", "История"],
          ["live", "Live-хвост"],
        ] as [LogsMode, string][]
      ).map(([m, label]) => (
        <button
          key={m}
          type="button"
          onClick={() => onChange(m)}
          className={cn(
            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            mode === m ? "bg-accent/15 text-accent" : "text-muted hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * Вкладка «Логи» (ТЗ §5.6): мини-график «логи по уровням» за 7 дней
 * (клик по дню → фильтр), навигация по дням «< 10.07 2026 >», таблица с
 * фильтрами/страницами 100/250/500, Live-хвост (SSE), экспорт txt/csv,
 * автопарсинг stat-строк vLLM. Ретенция — 14 дней (api, logs.retention_days).
 */
export default function LogsPage() {
  const [mode, setMode] = useState<LogsMode>("history");
  const [day, setDay] = useState(() => startOfDaySec(Math.floor(Date.now() / 1000)));
  const todayStart = startOfDaySec(Math.floor(Date.now() / 1000));

  const from = day;
  const to = day + DAY_S - 1;
  // окно мини-графика: CHART_DAYS дней, заканчивая выбранным днём
  const statsFrom = day - (CHART_DAYS - 1) * DAY_S;

  const { data: stats, error: statsError } = usePoll<LogsStatsData>(
    logsStatsUrl(statsFrom, to),
    30_000,
  );
  const { data: sourcesData } = usePoll<LogSourcesData>(LOGS_SOURCES_URL, 30_000);

  const offlineSources = (sourcesData?.sources ?? []).filter((s) => s.status === "offline");
  const dayStat = stats?.by_day.find((d) => d.day === day);
  const dayErrors = dayStat != null ? (dayStat.levels.ERROR ?? 0) + (dayStat.levels.CRITICAL ?? 0) : 0;
  const dayTotal = dayStat?.total ?? 0;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Логи</h1>
        <ModeToggle mode={mode} onChange={setMode} />
      </div>

      {offlineSources.length > 0 && (
        <InfoBanner
          message={`Источники логов offline: ${offlineSources
            .map((s) => `${s.name}${s.last_error != null ? ` — ${s.last_error}` : ""}`)
            .join("; ")}`}
        />
      )}
      {statsError != null && <ErrorBanner message={statsError} />}

      {mode === "history" ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-panel p-3">
            <div>
              <div className="text-sm font-medium">Логи по уровням · {CHART_DAYS} дней</div>
              <div className="text-xs text-muted">
                клик по дню — выбрать; ошибки дня — красным над баром
              </div>
            </div>
            {/* навигация по дням «< 10.07 2026 >» */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDay((d) => d - DAY_S)}
                className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs hover:border-accent/50 hover:text-accent"
              >
                ‹
              </button>
              <span className="min-w-28 text-center text-sm font-medium tabular-nums">
                {fmtDayFull(day)}
              </span>
              <button
                type="button"
                onClick={() => setDay((d) => d + DAY_S)}
                disabled={day >= todayStart}
                className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
              >
                ›
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-line bg-panel p-3">
            {stats?.by_day != null ? (
              <LogsDayChart
                byDay={stats.by_day}
                selectedDay={day}
                onSelectDay={setDay}
              />
            ) : (
              <div className="flex h-36 items-center justify-center text-sm text-muted">
                Загрузка…
              </div>
            )}
          </div>

          {/* счётчики ошибок за день (из /api/logs/stats) */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span
              className={cn(
                "rounded-md border px-2 py-1 font-medium",
                dayErrors > 0
                  ? "border-red-500/40 bg-red-500/10 text-red-400"
                  : "border-line bg-panel text-muted",
              )}
            >
              Ошибок за день: {dayErrors}
            </span>
            <span className="text-muted">
              строк за день: <span className="tabular-nums text-foreground">{dayTotal}</span>
            </span>
          </div>

          <LogsHistory from={from} to={to} />
        </div>
      ) : (
        <LogsLive />
      )}
    </div>
  );
}
