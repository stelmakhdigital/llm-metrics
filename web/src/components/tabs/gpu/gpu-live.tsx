"use client";

import { useMemo } from "react";
import UPlotChart from "@/components/charts/UPlotChart";
import { Card, CardContent } from "@/components/ui/card";
import { GpuCard } from "@/components/tabs/gpu/gpu-card";
import { fmtClock, useLive, useNow } from "@/lib/live";
import { cn } from "@/lib/utils";

/**
 * Вкладка «GPU», режим Live: KPI «весь GPU» (мощность + VRAM), живой график
 * суммарной мощности (powerHistory, окно до 5 мин), сетка карточек GPU 2×N.
 * Источник GPU offline — баннер + заглушки.
 */
export function GpuLive() {
  const { packet, connected, lastUpdate, powerHistory } = useLive();
  useNow(1000); // тик раз в секунду для индикатора «каждые 2 c ЧЧ:ММ:СС»

  const gpus = packet?.gpus ?? null;
  const total = packet?.gpu_total ?? null;
  const model = packet?.model ?? null;
  const gpuOffline = packet != null && packet.sources?.gpu === "offline";

  const limitsSum = useMemo(
    () => (gpus ? gpus.reduce((s, g) => s + (g.power_limit_w ?? 0), 0) : null),
    [gpus],
  );

  if (packet === null) {
    return (
      <Card>
        <CardContent className="flex h-40 items-center justify-center gap-3 text-sm text-muted">
          <span className="size-2 animate-pulse rounded-full bg-accent" aria-hidden />
          {connected ? "Ожидание первого пакета /api/live…" : "Подключение к /api/live…"}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">Мониторинг в реальном времени</h2>
              <p className="text-xs text-muted">
                Вся аппаратура: {gpus ? `${gpus.length} GPU` : "—"}
                {model ? ` · модель ${model}` : ""}
              </p>
            </div>
            <span className="flex items-center gap-1.5 text-xs text-muted">
              <span
                aria-hidden
                className={cn(
                  "size-1.5 rounded-full",
                  connected ? "bg-emerald-400" : "bg-red-400",
                )}
              />
              каждые 2 c
              <span className="tabular-nums text-foreground">{fmtClock(lastUpdate)}</span>
            </span>
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <div>
              <p className="text-xs text-muted">Суммарная мощность всего GPU</p>
              <p className="mt-1 text-4xl font-semibold tabular-nums">
                {total ? Math.round(total.power_w) : "—"}
                <span className="ml-1 text-base font-normal text-muted">W</span>
              </p>
              <p className="mt-1 text-xs text-muted">
                Лимит суммарной мощности{" "}
                {limitsSum != null && gpus ? Math.round(limitsSum) : "—"} W ·{" "}
                {gpus ? `${gpus.length} GPU` : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">Использовано VRAM</p>
              <p className="mt-1 text-4xl font-semibold tabular-nums">
                {total ? (total.mem_used_mib / 1024).toFixed(1) : "—"}
                <span className="ml-1 text-base font-normal text-muted">
                  / {total ? Math.round(total.mem_total_mib / 1024) : "—"} GiB
                </span>
              </p>
              <p className="mt-1 text-xs text-muted">
                физическая VRAM-занятость, включая KV-кэш
              </p>
            </div>
          </div>

          {powerHistory.length > 1 ? (
            <>
              <UPlotChart
                series={[
                  {
                    name: "Суммарная мощность W",
                    color: "#f97316",
                    points: powerHistory.map((p) => [p.ts, p.power_w] as [number, number]),
                  },
                ]}
                height={200}
                live
              />
              <p className="text-xs text-muted">
                live · суммарная board-мощность всех GPU · окно до 5 мин
              </p>
            </>
          ) : (
            <div className="flex h-[200px] items-center justify-center rounded-lg border border-line bg-panel2 text-xs text-muted">
              {gpuOffline ? "нет данных: источник GPU оффлайн" : "нет данных о мощности пока"}
            </div>
          )}
        </CardContent>
      </Card>

      {gpuOffline ? (
        <Card className="border-red-500/40">
          <CardContent className="py-8 text-center text-sm text-red-400">
            источник GPU оффлайн
          </CardContent>
        </Card>
      ) : gpus && gpus.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {gpus.map((g) => (
            <GpuCard key={g.id} gpu={g} model={model} />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted">
            нет данных о GPU
          </CardContent>
        </Card>
      )}
    </div>
  );
}
