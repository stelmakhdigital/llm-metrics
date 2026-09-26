"use client";

import { useEffect, useRef, useState } from "react";
import UPlotChart, { type ChartSeries } from "@/components/charts/UPlotChart";
import { Card, CardContent } from "@/components/ui/card";
import type { MetricPoint } from "@/lib/types";

/** Сведения о GPU из GET /api/gpus (для подписей серий). */
type GpuInfo = { id: number; name?: string | null; pci?: string | null };

const PALETTE = [
  "#f97316",
  "#38bdf8",
  "#a3e635",
  "#c084fc",
  "#fb7185",
  "#facc15",
  "#34d399",
  "#f472b6",
];

const METRICS = [
  { id: "gpu_power", label: "мощность W" },
  { id: "gpu_util", label: "утилизация %" },
  { id: "gpu_mem_used_mib", label: "VRAM MiB" },
  { id: "gpu_temp", label: "температура °C" },
  { id: "gpu_sm_clock", label: "SM clock MHz" },
] as const;

type MetricId = (typeof METRICS)[number]["id"];

/** КPI сверху — средние по этим метрикам (даже если чекбокс не выбран). */
const KPI_METRICS: { id: MetricId; label: string; fmt: (v: number) => string; unit: string }[] = [
  { id: "gpu_power", label: "Средняя мощность", fmt: (v) => String(Math.round(v)), unit: "W" },
  { id: "gpu_util", label: "Средняя утилизация", fmt: (v) => `${Math.round(v)}`, unit: "%" },
  {
    id: "gpu_mem_used_mib",
    label: "Средний VRAM",
    fmt: (v) => (v / 1024).toFixed(1),
    unit: "GiB",
  },
  { id: "gpu_temp", label: "Средняя температура", fmt: (v) => String(Math.round(v)), unit: "°C" },
];

function gpuLabel(g: GpuInfo): string {
  return `GPU ${g.id} · ${g.name ?? g.pci ?? "—"}`;
}

function parsePoints(json: unknown): MetricPoint[] {
  const arr: unknown = Array.isArray(json)
    ? json
    : ((json as { points?: unknown; series?: unknown })?.points ??
      (json as { points?: unknown; series?: unknown })?.series ??
      []);
  if (!Array.isArray(arr)) return [];
  return (arr as { ts?: number; value?: number | null }[])
    .filter((p) => typeof p?.ts === "number")
    .map((p) => ({
      ts: p.ts as number,
      value: typeof p.value === "number" ? p.value : null,
    }));
}

async function fetchPoints(
  metric: MetricId,
  from: number,
  to: number,
  gpu: number,
): Promise<MetricPoint[]> {
  const qs = new URLSearchParams({ from: String(from), to: String(to), gpu: String(gpu) });
  const res = await fetch(`/api/metrics/${metric}?${qs.toString()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return parsePoints(await res.json());
}

function average(pointsByGpu: Record<number, MetricPoint[]> | undefined): number | null {
  if (!pointsByGpu) return null;
  const values: number[] = [];
  for (const pts of Object.values(pointsByGpu)) {
    for (const p of pts) if (p.value != null) values.push(p.value);
  }
  if (values.length === 0) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function Skeleton() {
  return <div className="h-40 animate-pulse rounded-lg bg-panel2" aria-hidden />;
}

/**
 * Вкладка «GPU», период (не Live): KPI = средние за период, графики по GPU
 * (одна линия на GPU/метрику, выбор метрик — чекбоксы). Данные:
 * GET /api/metrics/{metric}?from&to&gpu={n} + подписи из GET /api/gpus.
 */
export function GpuPeriod({ from, to }: { from: number; to: number }) {
  const [gpus, setGpus] = useState<GpuInfo[]>([]);
  const [gpusError, setGpusError] = useState<string | null>(null);
  const [loadingGpus, setLoadingGpus] = useState(true);
  const [selected, setSelected] = useState<string[]>(["gpu_power", "gpu_util"]);
  const [data, setData] = useState<Partial<Record<MetricId, Record<number, MetricPoint[]>>>>({});
  const [pointErrors, setPointErrors] = useState<Set<string>>(new Set());
  const [loadingPoints, setLoadingPoints] = useState(false);
  const cacheRef = useRef<Partial<Record<string, MetricPoint[]>>>({});

  // список GPU для подписей (pci/имя)
  useEffect(() => {
    let cancelled = false;
    setLoadingGpus(true);
    (async () => {
      try {
        const res = await fetch("/api/gpus");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const j = await res.json();
        const list: unknown = Array.isArray(j) ? j : (j as { gpus?: unknown })?.gpus;
        const parsed = (Array.isArray(list) ? list : [])
          .filter((g): g is GpuInfo => typeof (g as GpuInfo)?.id === "number")
          .slice(0, 8);
        if (!cancelled) {
          setGpus(parsed);
          setGpusError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setGpus([]);
          setGpusError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setLoadingGpus(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [from, to]);

  // серии по выбранным + KPI-метрикам для каждого GPU
  const selectedKey = [...selected].sort().join(",");
  useEffect(() => {
    if (gpus.length === 0) return;
    let cancelled = false;
    setLoadingPoints(true);
    const needed = new Set<string>([
      ...(selectedKey ? selectedKey.split(",") : []),
      ...KPI_METRICS.map((k) => k.id),
    ]);
    (async () => {
      for (const m of METRICS) {
        if (!needed.has(m.id) || cancelled) continue;
        const rows: Record<number, MetricPoint[]> = {};
        await Promise.all(
          gpus.map(async (g) => {
            const cacheKey = `${m.id}:${g.id}`;
            const cached = cacheRef.current[cacheKey];
            if (cached) {
              rows[g.id] = cached;
              return;
            }
            try {
              const pts = await fetchPoints(m.id, from, to, g.id);
              cacheRef.current[cacheKey] = pts;
              rows[g.id] = pts;
            } catch {
              if (!cancelled) {
                setPointErrors((prev) => new Set(prev).add(cacheKey));
              }
            }
          }),
        );
        if (!cancelled) {
          setData((prev) => ({ ...prev, [m.id]: rows }));
        }
      }
      if (!cancelled) setLoadingPoints(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [from, to, gpus, selectedKey]);

  const toggle = (id: string) =>
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  return (
    <div className="space-y-4">
      {gpusError && (
        <Card className="border-red-500/40">
          <CardContent className="py-3 text-sm text-red-400">
            ошибка загрузки списка GPU (/api/gpus): {gpusError}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {KPI_METRICS.map((k) => {
          const v = average(data[k.id]);
          return (
            <Card key={k.id}>
              <CardContent className="p-4">
                <p className="text-xs text-muted">{k.label}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">
                  {v != null ? k.fmt(v) : "—"}
                  <span className="ml-1 text-sm font-normal text-muted">{k.unit}</span>
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {pointErrors.size > 0 && (
        <Card className="border-red-500/40">
          <CardContent className="py-3 text-sm text-red-400">
            не удалось загрузить {pointErrors.size} серию(й) /api/metrics
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Метрики по GPU</h2>
            <div className="flex flex-wrap items-center gap-3">
              {METRICS.map((m) => (
                <label
                  key={m.id}
                  className="flex cursor-pointer items-center gap-1.5 text-xs text-muted hover:text-foreground"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(m.id)}
                    onChange={() => toggle(m.id)}
                    className="size-3.5 accent-[#f97316]"
                  />
                  {m.label}
                </label>
              ))}
            </div>
          </div>

          {loadingGpus ? (
            <Skeleton />
          ) : gpus.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted">
              {gpusError ? "нет данных" : "нет GPU в /api/gpus"}
            </p>
          ) : (
            <div className="space-y-5">
              {METRICS.filter((m) => selected.includes(m.id)).map((m) => {
                const rows = data[m.id];
                const series: ChartSeries[] = gpus.map((g, i) => ({
                  name: gpuLabel(g),
                  color: PALETTE[i % PALETTE.length],
                  points: (rows?.[g.id] ?? []).map((p) => [p.ts, p.value]),
                }));
                const hasPoints = series.some((s) => s.points.length > 0);
                return (
                  <div key={m.id}>
                    <p className="mb-1 text-xs text-muted">{m.label}</p>
                    {loadingPoints && !rows ? (
                      <Skeleton />
                    ) : hasPoints ? (
                      <UPlotChart series={series} height={240} />
                    ) : (
                      <div className="flex h-[240px] items-center justify-center rounded-lg border border-line bg-panel2 text-xs text-muted">
                        нет данных
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
