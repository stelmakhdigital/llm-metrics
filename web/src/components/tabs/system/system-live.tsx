"use client";

import { useLive } from "@/lib/live";
import {
  usePoll,
  type SystemSnapshot,
  type TopProcRow,
} from "@/lib/api";
import {
  fmtInt,
  fmtMhz,
  fmtMbS,
  fmtMbps,
  fmtMb,
  NA,
} from "@/lib/format";
import {
  ChartCard,
  ErrorBanner,
  InfoBanner,
  KpiCard,
  NoData,
  SkeletonKpi,
} from "../common";
import { cn } from "@/lib/utils";

/** Период опроса /api/system в Live-режиме, мс. */
export const SYSTEM_POLL_MS = 5_000;

function TopProcesses({ title, rows }: { title: string; rows: TopProcRow[] }) {
  return (
    <ChartCard title={title}>
      {rows.length === 0 ? (
        <NoData />
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="pb-1 pr-2 font-medium">PID</th>
              <th className="pb-1 pr-2 font-medium">Процесс</th>
              <th className="pb-1 pr-2 text-right font-medium">RAM, MiB</th>
              <th className="pb-1 text-right font-medium">CPU, %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([pid, name, rss, cpu]) => (
              <tr key={pid} className="border-t border-line/50">
                <td className="py-1 pr-2 text-muted">{pid}</td>
                <td className="max-w-[16rem] truncate py-1 pr-2" title={name}>
                  {name}
                </td>
                <td className="py-1 pr-2 text-right tabular-nums">{fmtInt(rss)}</td>
                <td className="py-1 text-right tabular-nums">{cpu.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ChartCard>
  );
}

function DiskBars({ disks, title }: { disks: SystemSnapshot["disks"]; title: string }) {
  return (
    <ChartCard title={title}>
      {disks.length === 0 ? (
        <NoData text="Монтировки не найдены" />
      ) : (
        <div className="space-y-2">
          {disks.map((d) => (
            <div key={d.mount}>
              <div className="mb-0.5 flex items-center justify-between text-xs">
                <span className="text-muted">{d.mount}</span>
                <span className="tabular-nums">{d.used_pct.toFixed(0)}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                <div
                  className={cn(
                    "h-full rounded-full",
                    d.used_pct >= 90 ? "bg-red-500" : d.used_pct >= 75 ? "bg-amber-400" : "bg-accent",
                  )}
                  style={{ width: `${Math.min(100, d.used_pct)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  );
}

/**
 * Вкладка «Система» в режиме Live: KPI + топ-5 процессов.
 * Источники — GET /api/system (poll раз в 5 с, поля — routes.py)
 * + статус источника из SSE-пакета (useLive).
 */
export function SystemLive() {
  const { packet } = useLive();
  const { data, loading, error } = usePoll<SystemSnapshot>("/api/system", SYSTEM_POLL_MS);

  const sysOffline = packet != null && packet.sources?.system === "offline";

  return (
    <div className="space-y-3">
      {sysOffline && (
        <InfoBanner message="Источник системы (system) оффлайн — данные не собираются." />
      )}
      {error != null && <ErrorBanner message={error} />}

      {loading && !data ? (
        <SkeletonKpi rows={8} />
      ) : data ? (
        <>
          <div className="flex items-center justify-between">
            <div className="text-xs text-muted">
              обновлено: {new Date(data.ts * 1000).toLocaleTimeString("ru-RU")} (poll 5 с)
            </div>
            {sysOffline && <span className="text-xs text-amber-400">источник offline</span>}
          </div>

          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <KpiCard
              label="CPU"
              value={data.cpu.usage == null ? NA : `${data.cpu.usage.toFixed(1)}%`}
              sub={`steal: ${data.cpu.steal_pct == null ? NA : `${data.cpu.steal_pct.toFixed(1)}%`}`}
            />
            <KpiCard
              label="Load average (1/5/15)"
              value={
                data.cpu.load.every((v) => v == null)
                  ? NA
                  : data.cpu.load.map((v) => (v == null ? NA : v.toFixed(2))).join(" / ")
              }
            />
            <KpiCard
              label="RAM (used / total)"
              value={
                data.ram.used_mb == null || data.ram.total_mb == null
                  ? NA
                  : `${fmtMb(data.ram.used_mb)} / ${fmtMb(data.ram.total_mb)}`
              }
            >
              {data.ram.used_mb != null && data.ram.total_mb ? (
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{
                      width: `${Math.min(100, (data.ram.used_mb / data.ram.total_mb) * 100)}%`,
                    }}
                  />
                </div>
              ) : null}
            </KpiCard>
            <KpiCard
              label="Swap used"
              value={fmtMb(data.ram.swap_used_mb)}
              sub={`свободно: ${fmtMb(data.ram.available_mb)}`}
            />
            <KpiCard
              label="CPU freq"
              value={fmtMhz(data.cpu.freq_mhz)}
            />
            <KpiCard
              label="Сеть (rx / tx)"
              value={`${fmtMbps(data.net.rx_mbps)} / ${fmtMbps(data.net.tx_mbps)}`}
            />
            <KpiCard
              label="Диск (read / write)"
              value={`${fmtMbS(data.io.read_mb_s)} / ${fmtMbS(data.io.write_mb_s)}`}
            />
            <KpiCard
              label="PSI (cpu/mem/io, 10s)"
              value={
                [data.psi.cpu?.avg10, data.psi.memory?.avg10, data.psi.io?.avg10]
                  .every((v) => v == null)
                  ? NA
                  : [data.psi.cpu?.avg10, data.psi.memory?.avg10, data.psi.io?.avg10]
                      .map((v) => (v == null ? NA : v.toFixed(2)))
                      .join(" / ")
                }
            />
          </div>

          {data.cpu.per_core.length > 0 && (
            <ChartCard
              title={`CPU по ядрам (${data.cpu.per_core.length})`}
              note="текущая загрузка по каждому логическому ядру, %"
            >
              <div className="flex h-24 items-end gap-0.5">
                {data.cpu.per_core.map((v, i) => (
                  <div
                    key={i}
                    className="flex h-full flex-1 items-end"
                    title={`core ${i}: ${v == null ? NA : `${v.toFixed(1)}%`}`}
                  >
                    <div
                      className={cn(
                        "w-full rounded-t",
                        v != null && v >= 90 ? "bg-red-500" : "bg-accent/80",
                      )}
                      style={{ height: `${v == null ? 0 : Math.max(2, v)}%` }}
                    />
                  </div>
                ))}
              </div>
            </ChartCard>
          )}

          <div className="grid gap-3 xl:grid-cols-2">
            <DiskBars disks={data.disks} title="Занятость дисков (mount'ы)" />
            <div className="grid gap-3">
              <TopProcesses title="Топ-5 процессов по CPU" rows={data.top_cpu} />
              <TopProcesses title="Топ-5 процессов по RAM" rows={data.top_ram} />
            </div>
          </div>
        </>
      ) : (
        !error && <NoData />
      )}
    </div>
  );
}
