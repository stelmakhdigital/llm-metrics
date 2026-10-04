"use client";

import { useEffect, useState } from "react";
import { usePeriod } from "@/lib/periods";
import { useRefresh } from "@/lib/refresh";
import { useLive } from "@/lib/live";
import {
  fetchJson,
  metricUrl,
  PALETTE,
  usePoll,
  type MetricResponse,
  type SystemSnapshot,
} from "@/lib/api";
import { fmtMb, NA } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ErrorBanner, InfoBanner, ChartCard, NoData } from "../common";
import { MetricChart, type MetricSpec } from "../metric-chart";

// ------------------------------------------------------------------- specs

const CPU_TOTAL: MetricSpec[] = [{ metric: "cpu_usage", label: "CPU, %", color: PALETTE[0] }];
const RAM_SPECS: MetricSpec[] = [
  { metric: "ram_used_mb", label: "занято, MB", color: PALETTE[0] },
  { metric: "ram_available_mb", label: "свободно, MB", color: PALETTE[1] },
];
const SWAP_SPECS: MetricSpec[] = [{ metric: "swap_used_mb", label: "swap used, MB", color: PALETTE[4] }];
const DISK_IO_SPECS: MetricSpec[] = [
  { metric: "disk_read_mb_s", label: "read, MB/s", color: PALETTE[1] },
  { metric: "disk_write_mb_s", label: "write, MB/s", color: PALETTE[0] },
];
const NET_SPECS: MetricSpec[] = [
  { metric: "net_rx_mbps", label: "rx, Мбит/с", color: PALETTE[2] },
  { metric: "net_tx_mbps", label: "tx, Мбит/с", color: PALETTE[3] },
];
const STEAL_SPECS: MetricSpec[] = [{ metric: "cpu_steal_pct", label: "steal, %", color: PALETTE[7] }];
const FREQ_SPECS: MetricSpec[] = [{ metric: "cpu_freq_mhz", label: "частота, МГц", color: PALETTE[5] }];

const PSI_KINDS = [
  { kind: "cpu", label: "PSI: CPU" },
  { kind: "io", label: "PSI: IO" },
  { kind: "memory", label: "PSI: memory" },
];
const PSI_TAILS = ["avg10", "avg60", "avg300"] as const;

function psiSpecs(kind: string): MetricSpec[] {
  return PSI_TAILS.map((tail, i) => ({
    metric: `psi_${kind}_${tail}`,
    label: `${tail} (some, %)`,
    color: PALETTE[i + 1],
  }));
}

/** CPU по ядрам: cpu_usage_core_{i}, i = 0..N-1 (N — из /api/system). */
function coreSpecs(cores: number): MetricSpec[] {
  return Array.from({ length: cores }, (_, i) => ({
    metric: `cpu_usage_core_${i}`,
    label: `К${i}`,
    color: PALETTE[i % PALETTE.length],
  }));
}

// ------------------------------------------------- disks (последнее значение)

function PeriodDisks({ from, to, mounts }: { from: number; to: number; mounts: string[] }) {
  const [rows, setRows] = useState<{ mount: string; pct: number | null }[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { tick: refreshTick } = useRefresh();

  useEffect(() => {
    if (mounts.length === 0) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setRows(null);
    setError(null);
    Promise.all(
      mounts.map((m) => fetchJson<MetricResponse>(metricUrl(`disk_used_pct|${m}`, from, to))),
    )
      .then((responses) => {
        if (cancelled) return;
        setRows(
          mounts.map((m, i) => {
            const pts = responses[i].points;
            let last: number | null = null;
            for (let j = pts.length - 1; j >= 0; j--) {
              if (pts[j][1] != null) {
                last = pts[j][1] as number;
                break;
              }
            }
            return { mount: m, pct: last };
          }),
        );
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка API");
      });
    return () => {
      cancelled = true;
    };
  }, [mounts, from, to, refreshTick]);

  return (
    <ChartCard title="Занятость дисков (последнее значение периода)" tip="Занятость дисковых пространств по mount-точкам, %. Последняя точка за период.">
      {error != null ? (
        <ErrorBanner message={error} />
      ) : rows == null ? (
        <NoData text="Загрузка…" />
      ) : rows.length === 0 ? (
        <NoData text="Монтировки не найдены" />
      ) : (
        <div className="space-y-2">
          {rows.map((d) => (
            <div key={d.mount}>
              <div className="mb-0.5 flex items-center justify-between text-xs">
                <span className="text-muted">{d.mount}</span>
                <span className="tabular-nums">{d.pct == null ? NA : `${d.pct.toFixed(0)}%`}</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                <div
                  className={cn(
                    "h-full rounded-full",
                    d.pct != null && d.pct >= 90
                      ? "bg-red-500"
                      : d.pct != null && d.pct >= 75
                        ? "bg-amber-400"
                        : "bg-accent",
                  )}
                  style={{ width: `${d.pct == null ? 0 : Math.min(100, d.pct)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  );
}

// ------------------------------------------------------------------- page

/**
 * Вкладка «Система» в режиме периода: графики /api/metrics/{metric}?from&to
 * (метрики — api/app/collectors/system.py) + занятость дисков по mount-ам.
 */
export function SystemPeriod() {
  const { period, from, to } = usePeriod();
  const { packet } = useLive();
  const rangeOk = from != null && to != null && to > from;
  const sysOffline = packet != null && packet.sources?.system === "offline";

  // /api/system (разово): число ядер + список mount-ов для disk_used_pct
  const { data: snap } = usePoll<SystemSnapshot>("/api/system", 0);
  const coreCount = snap?.cpu.per_core.length ?? 0;
  const mounts = snap?.disks.map((d) => d.mount) ?? [];

  const [cpuMode, setCpuMode] = useState<"total" | "cores">("total");
  const cpuSpecs = cpuMode === "cores" && coreCount > 0 ? coreSpecs(coreCount) : CPU_TOTAL;

  if (!rangeOk) {
    return (
      <InfoBanner
        message={
          period === "custom"
            ? "Выберите произвольный диапазон дат в переключателе периода."
            : "Период не задан."
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      {sysOffline && (
        <InfoBanner message="Источник системы (system) оффлайн — часть графиков может быть без данных." />
      )}

      <ChartCard
        title="CPU, %"
        tip="Общая загрузка CPU за период, %. Среднее по ядрам."
        legend={
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setCpuMode("total")}
              className={cn(
                "rounded-md px-2 py-0.5 text-xs",
                cpuMode === "total"
                  ? "bg-accent/15 text-accent"
                  : "text-muted hover:text-foreground",
              )}
            >
              общая
            </button>
            <button
              type="button"
              onClick={() => coreCount > 0 && setCpuMode("cores")}
              disabled={coreCount === 0}
              className={cn(
                "rounded-md px-2 py-0.5 text-xs",
                cpuMode === "cores"
                  ? "bg-accent/15 text-accent"
                  : "text-muted hover:text-foreground",
                coreCount === 0 && "cursor-not-allowed opacity-50",
              )}
            >
              по ядрам {coreCount > 0 ? `(${coreCount})` : "— нет данных"}
            </button>
          </div>
        }
      >
        <MetricChart
          title={cpuMode === "cores" ? `CPU по ядрам (${coreCount})` : "CPU (общая загрузка)"}
          tip={cpuMode === "cores" ? "Загрузка каждого ядра CPU, % (последние ядра — гиперпотоки)." : "Общая загрузка CPU, %."}
          specs={cpuSpecs}
          from={from}
          to={to}
          height={cpuMode === "cores" ? 260 : 220}
        />
      </ChartCard>

      <div className="grid gap-3 xl:grid-cols-2">
        <MetricChart
          title="RAM, MB"
          tip="Занятая оперативная память, МБ."
          specs={RAM_SPECS}
          from={from}
          to={to}
          note={`текущее (live): занято ${fmtMb(snap?.ram.used_mb ?? null)} из ${fmtMb(snap?.ram.total_mb ?? null)}`}
        />
        <MetricChart title="Swap used, MB" specs={SWAP_SPECS} from={from} to={to} tip="Использованный swap (файл/раздел подкачки), МБ."
          />
        <MetricChart title="Диск: read / write, MB/s" specs={DISK_IO_SPECS} from={from} to={to} tip="Скорость чтения/записи всех дисков, МБ/с."
          />
        <MetricChart title="Сеть: rx / tx, Мбит/с" specs={NET_SPECS} from={from} to={to} tip="Сетевой трафик: входящий (rx) и исходящий (tx), Мбит/с."
          />
        <MetricChart title="CPU steal, %" specs={STEAL_SPECS} from={from} to={to} tip="Доля времени, когда CPU ждал процессоры у хост-гипервизора (VM). 0 — не виртуализация/нет конкуренции."
          />
        <MetricChart title="Частота CPU, МГц" specs={FREQ_SPECS} from={from} to={to} tip="Средняя частота CPU, МГц. Снижается при экономии энергии или перегреве."
          />
        {PSI_KINDS.map((k) => (
          <MetricChart
            key={k.kind}
            title={`${k.label}: some, %`}
            tip={`Доля времени в состоянии «${k.label}» (ожидание), %.`}
            specs={psiSpecs(k.kind)}
            from={from}
            to={to}
          />
        ))}
      </div>

      <PeriodDisks from={from} to={to} mounts={mounts} />
    </div>
  );
}
