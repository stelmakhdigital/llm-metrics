"use client";

import { GpuLive } from "@/components/tabs/gpu/gpu-live";
import { GpuPeriod } from "@/components/tabs/gpu/gpu-period";
import { usePeriod } from "@/lib/periods";

/** Вкладка «GPU»: Live (SSE) при периоде live, иначе период — по /api/metrics. */
export default function GpuPage() {
  const { period, from, to } = usePeriod();

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold">GPU</h1>
      {period === "live" ? (
        <GpuLive />
      ) : from != null && to != null ? (
        <GpuPeriod from={from} to={to} />
      ) : (
        <p className="rounded-lg border border-line bg-panel p-6 text-center text-sm text-muted">
          Выберите период или задайте произвольный диапазон.
        </p>
      )}
    </div>
  );
}
