"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  HEALTH_SUMMARY_URL,
  usePoll,
  type HealthSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { fmtAgo, fmtW, fmtNum } from "@/lib/format";
import { ErrorBanner, InfoBanner } from "../common";
import { cn } from "@/lib/utils";

function uptimeFmt(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}д ${h}ч ${m}м`;
  if (h > 0) return `${h}ч ${m}м`;
  return `${m}м`;
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    online: "bg-emerald-400",
    offline: "bg-red-400",
    unknown: "bg-muted/50",
  };
  return (
    <Badge variant="outline" className="gap-1.5 text-[11px]">
      <span className={cn("size-1.5 rounded-full", map[status] ?? "bg-muted/50")} aria-hidden />
      {status === "online" ? "online" : status === "offline" ? "оффлайн" : "unknown"}
    </Badge>
  );
}

/** Вкладка «Health» (F4.3): сводный статус без глубокого дайвинга. */
export function HealthTab() {
  const { data, loading, error } = usePoll<HealthSummary>(HEALTH_SUMMARY_URL, 30_000);

  const sourceRows = useMemo(() => {
    if (!data) return [];
    const { last_sample_ts, ...statuses } = data.sources;
    return Object.entries(statuses).map(([name, s]) => ({
      name,
      status: s.status,
      lastOk: s.last_ok_ts,
      lastError: s.last_error,
      lastSample: last_sample_ts[name] ?? null,
    }));
  }, [data]);

  if (error != null && !data) return <ErrorBanner message={error} />;
  if (!data)
    return (
      <div className="h-60 animate-pulse rounded-xl border border-line bg-panel2" />
    );

  const s = data.service;

  return (
    <div className="space-y-3">
      {error != null && <ErrorBanner message={error} />}
      {!loading && error == null && null}

      <div className="grid gap-3 lg:grid-cols-2">
        {/* Сервис */}
        <section className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-medium">Сервис</h2>
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Версия</dt>
              <dd>{s.version}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Аптайм</dt>
              <dd>{uptimeFmt(s.uptime_s)}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="shrink-0 text-muted">БД</dt>
              <dd className="truncate" title={s.db_path}>
                {s.db_path}
                {s.db_size_mb != null && ` (${s.db_size_mb} МБ)`}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted">Выборок / логов</dt>
              <dd>
                {s.counts["metric_samples"] ?? "—"} / {s.counts["log_entries"] ?? "—"}
              </dd>
            </div>
          </dl>
        </section>

        {/* Модель */}
        <section className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-medium">Модель vLLM</h2>
          {data.model ? (
            <div className="text-sm">{data.model}</div>
          ) : (
            <div className="text-sm text-muted">нет данных (источник оффлайн?)</div>
          )}
          <div className="mt-3 flex items-center gap-2 text-sm">
            <span className="text-muted">Активных алертов:</span>
            <Link
              href="/alerts"
              className={cn(
                "font-medium underline-offset-2 hover:underline",
                data.alerts_active > 0 ? "text-red-400" : "text-emerald-400",
              )}
            >
              {data.alerts_active}
            </Link>
          </div>
        </section>
      </div>

      {/* Источники */}
      <section className="rounded-xl border border-line bg-panel p-4">
        <h2 className="mb-2 text-sm font-medium">Источники</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-1 pr-2 font-normal">Источник</th>
              <th className="py-1 pr-2 font-normal">Статус</th>
              <th className="py-1 pr-2 font-normal">Последний опрос ok</th>
              <th className="py-1 pr-2 font-normal">Последняя выборка</th>
              <th className="py-1 font-normal">Ошибка</th>
            </tr>
          </thead>
          <tbody>
            {sourceRows.map((r) => (
              <tr key={r.name} className="border-t border-line">
                <td className="py-1.5 pr-2">{r.name}</td>
                <td className="py-1.5 pr-2">
                  <StatusChip status={r.status} />
                </td>
                <td className="py-1.5 pr-2 text-muted">{fmtAgo(r.lastOk)}</td>
                <td className="py-1.5 pr-2 text-muted">{fmtAgo(r.lastSample)}</td>
                <td className="max-w-md truncate py-1.5 text-xs text-muted" title={r.lastError ?? ""}>
                  {r.lastError ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        {/* GPU */}
        <section className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-medium">GPU</h2>
          {data.gpus.length === 0 ? (
            <div className="text-sm text-muted">нет данных</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="py-1 pr-2 font-normal">GPU</th>
                  <th className="py-1 pr-2 font-normal">P, Вт</th>
                  <th className="py-1 pr-2 font-normal">T, °C</th>
                  <th className="py-1 pr-2 font-normal">VRAM</th>
                  <th className="py-1 pr-2 font-normal">Троттлинг</th>
                  <th className="py-1 font-normal">ECC (неиспр.)</th>
                </tr>
              </thead>
              <tbody>
                {data.gpus.map((g) => (
                  <tr key={g.id ?? g.name} className="border-t border-line">
                    <td className="max-w-40 truncate py-1.5 pr-2" title={g.name ?? ""}>
                      {g.name ?? `#${g.id}`}
                    </td>
                    <td className="py-1.5 pr-2">{fmtW(g.power_w)}</td>
                    <td className="py-1.5 pr-2">{fmtNum(g.temp_c, 0)} °C</td>
                    <td className="py-1.5 pr-2">{fmtNum(g.mem_used_pct, 1)}%</td>
                    <td
                      className={cn(
                        "py-1.5 pr-2",
                        g.throttle.length > 0 && "text-amber-400",
                      )}
                    >
                      {g.throttle.length > 0 ? g.throttle.join(", ") : "—"}
                    </td>
                    <td className="py-1.5">{fmtNum(g.ecc_uncorrectable, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Система + логи */}
        <section className="rounded-xl border border-line bg-panel p-4">
          <h2 className="mb-2 text-sm font-medium">Система и логи</h2>
          <div className="space-y-1 text-sm">
            {data.system.disks.length === 0 && (
              <div className="text-muted">диски: нет данных</div>
            )}
            {data.system.disks.map((d) => (
              <div key={d.mount} className="flex justify-between gap-4">
                <span className="text-muted">Диск {d.mount}</span>
                <span className={cn(d.used_pct >= 90 && "text-red-400")}>
                  {fmtNum(d.used_pct, 1)}%
                </span>
              </div>
            ))}
            <hr className="my-2 border-line" />
            <div className="flex justify-between gap-4">
              <span className="text-muted">Ошибки логов (24ч)</span>
              <span className={cn(data.logs.errors_24h > 0 && "text-red-400")}>
                {data.logs.errors_24h}
              </span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted">Критичные (24ч)</span>
              <span className={cn(data.logs.critical_24h > 0 && "text-red-400")}>
                {data.logs.critical_24h}
              </span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted">Предупреждения (24ч)</span>
              <span>{data.logs.warnings_24h}</span>
            </div>
          </div>
        </section>
      </div>

      {data.model == null && (
        <InfoBanner message="Модель vLLM недоступна — источник vllm оффлайн или ещё не собрал данные." />
      )}
    </div>
  );
}
