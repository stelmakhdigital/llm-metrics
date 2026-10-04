"use client";

import { useLive } from "@/lib/live";
import { NA, fmtTimeS } from "@/lib/format";
import { InfoBanner, SkeletonKpi } from "../common";
import { KpiGrid, liveKpiCards } from "./kpi";

/**
 * Вкладка «Модель» в режиме Live: KPI + p50 из SSE (useLive, пакет раз в ~2 с).
 * Опроса /api/model нет — все live-значения приходят push-ом.
 * Причины финиша — в режиме периода (окно от 5 мин).
 */
export function ModelLive() {
  const { packet, connected, lastUpdate } = useLive();

  const vllmOffline = packet != null && packet.sources?.vllm === "offline";

  // p50 — теперь в SSE-пакете (kpi.ttft_p50 / kpi.tpot_p50); опроса /api/model нет
  const p50 =
    packet?.kpi != null
      ? { ttft: packet.kpi.ttft_p50 ?? null, tpot: packet.kpi.tpot_p50 ?? null }
      : null;

  return (
    <div className="space-y-3">
      {!connected && (
        <InfoBanner message="Соединение с сервером метрик не установлено — ждём SSE…" />
      )}
      {vllmOffline && (
        <InfoBanner message="Источник vLLM оффлайн — KPI модели недоступны." />
      )}

      {packet == null ? (
        <SkeletonKpi rows={8} />
      ) : (
        <div className="flex items-center justify-between">
          <div className="text-sm">
            <span className="text-muted">Модель: </span>
            <span className="font-medium">{packet.model ?? NA}</span>
          </div>
          <div className="text-xs text-muted">
            обновлено: {fmtTimeS(lastUpdate)}
          </div>
        </div>
      )}

      {packet != null && !vllmOffline && (
        <KpiGrid cards={liveKpiCards(packet.kpi, p50)} />
      )}

      <div className="grid gap-3 lg:grid-cols-[320px_1fr]">
        <div className="rounded-xl border border-line bg-panel p-3 text-xs leading-relaxed text-muted">
          <div className="mb-1 text-sm font-medium text-foreground">Причины финиша</div>
          Распределение finish reasons считается по данным окна периода
          (5 мин / 1 час / …) и показывается в режиме периода. В Live-режиме
          не опрашивается — чтобы не дублировать SSE push.
        </div>
        <div className="rounded-xl border border-line bg-panel p-3 text-xs leading-relaxed text-muted">
          <div className="mb-1 text-sm font-medium text-foreground">Live (SSE)</div>
          KPI (включая p50-квантили) обновляются каждые ~2 с (пакет /api/live).
          <div className="mt-2">
            Ключи KPI (контракт SSE): running, waiting, prompt_rate, gen_rate,
            kv_cache, prefix_hit_rate, ttft_p95, ttft_p50, tpot_p95, tpot_p50,
            e2e_p95, preemptions_rate. Ключа «запросы/с» в live-пакете нет —
            карточка «Запросы/с» показывается в режиме периода (сумма
            requests_finished / длительность).
          </div>
        </div>
      </div>
    </div>
  );
}
