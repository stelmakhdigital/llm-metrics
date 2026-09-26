"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { GpuSnapshot } from "@/lib/live";
import { cn } from "@/lib/utils";

function gib(mib: number | null): string {
  return mib == null ? "—" : (mib / 1024).toFixed(1);
}

/**
 * Карточка одного GPU (Live): power + лимит, VRAM-бар, утилизация SM,
 * температура + частоты, троттлинг (красный бейдж + подсветка), ECC-счётчик.
 * Нет данных — «—».
 */
export function GpuCard({ gpu, model }: { gpu: GpuSnapshot; model: string | null }) {
  const throttle = gpu.throttle ?? [];
  const throttling = throttle.length > 0;
  const eccUncorrectable = gpu.ecc_uncorrectable ?? 0;

  const memPct =
    gpu.mem_used_mib != null && gpu.mem_total_mib != null && gpu.mem_total_mib > 0
      ? (gpu.mem_used_mib / gpu.mem_total_mib) * 100
      : null;

  return (
    <Card className={cn(throttling && "ring-1 ring-red-500/50")}>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">GPU {gpu.id}</span>
          {model ? <Badge variant="accent">в работе модели</Badge> : null}
          <span className="ml-auto text-xs text-muted">{gpu.name ?? `PCI ${gpu.id}`}</span>
        </div>

        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-3xl font-semibold tabular-nums">
            {gpu.power_w != null ? Math.round(gpu.power_w) : "—"}
          </span>
          <span className="text-sm text-muted">W</span>
          <span className="text-xs text-muted">
            лимит {gpu.power_limit_w != null ? Math.round(gpu.power_limit_w) : "—"} W
          </span>
        </div>

        <div>
          <div className="mb-1 flex items-baseline justify-between text-xs">
            <span className="text-muted">VRAM</span>
            <span className="tabular-nums text-foreground">
              {gib(gpu.mem_used_mib)} / {gib(gpu.mem_total_mib)} GiB
            </span>
          </div>
          <Progress value={memPct ?? 0} size="sm" />
        </div>

        <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
          <span className="text-muted">
            утилизация SM{" "}
            <span className="tabular-nums text-foreground">
              {gpu.util != null ? `${gpu.util}%` : "—"}
            </span>
          </span>
          <span className="tabular-nums text-foreground">
            {gpu.temp != null ? `${gpu.temp} °C` : "—"} · {gpu.sm_clock_mhz ?? "—"} /{" "}
            {gpu.mem_clock_mhz ?? "—"} MHz
          </span>
        </div>

        {(throttling || eccUncorrectable > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {throttling && (
              <Badge variant="destructive">троттлинг: {throttle.join(", ")}</Badge>
            )}
            {eccUncorrectable > 0 && (
              <Badge variant="destructive">
                ECC некорректируемые: {eccUncorrectable}
              </Badge>
            )}
          </div>
        )}

        <p className="text-[11px] text-muted">
          ECC: {gpu.ecc_correctable ?? 0} корректируемых · {eccUncorrectable} некорректируемых
        </p>
      </CardContent>
    </Card>
  );
}
