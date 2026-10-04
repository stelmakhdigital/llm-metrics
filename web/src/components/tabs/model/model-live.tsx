"use client";

import {
  LIVE_REFRESH_MS,
  LIVE_WINDOW_S,
  modelUrl,
  useNow,
  usePoll,
  type ModelData,
} from "@/lib/api";
import { useLive } from "@/lib/live";
import { NA, fmtTimeS } from "@/lib/format";
import { ErrorBanner, InfoBanner, SkeletonKpi } from "../common";
import { FinishReasons } from "./finish-reasons";
import { KpiGrid, liveKpiCards } from "./kpi";

/**
 * Вкладка «Модель» в режиме Live: KPI из SSE (useLive, пакет раз в ~2 с) +
 * p50 и причины финиша — из /api/model за последние 5 минут (опрос раз в
 * минуту — контракт SSE даёт только p95 и не содержит finish reasons).
 */
export function ModelLive() {
  const { packet, connected, lastUpdate } = useLive();
  const now = useNow(LIVE_REFRESH_MS);
  const { data: m5, error: m5Error } = usePoll<ModelData>(
    modelUrl(now - LIVE_WINDOW_S, now),
    0,
  );

  const vllmOffline = packet != null && packet.sources?.vllm === "offline";

  const p50 =
    m5?.kpi != null
      ? { ttft: m5.kpi.ttft_p50, tpot: m5.kpi.tpot_p50 }
      : null;

  return (
    <div className="space-y-3">
      {!connected && (
        <InfoBanner message="Соединение с сервером метрик не установлено — ждём SSE…" />
      )}
      {vllmOffline && (
        <InfoBanner message="Источник vLLM оффлайн — KPI модели недоступны." />
      )}
      {m5Error != null && (
        <ErrorBanner message={`p50/причины финиша (за 5м): ${m5Error}`} />
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
        <FinishReasons reasons={m5?.kpi?.finish_reasons ?? null} />
        <div className="rounded-xl border border-line bg-panel p-3 text-xs leading-relaxed text-muted">
          <div className="mb-1 text-sm font-medium text-foreground">Live (SSE)</div>
          KPI обновляются каждые ~2 с (пакет /api/live). p50-квантили и причины
          финиша считаются по данным за последние 5 минут
          и обновляются раз в минуту.
          <div className="mt-2">
            Ключи KPI (контракт SSE): running, waiting, prompt_rate, gen_rate,
            kv_cache, prefix_hit_rate, ttft_p95, tpot_p95, e2e_p95,
            preemptions_rate. Ключа «запросы/с» в live-пакете нет — карточка
            «Запросы/с» показывается в режиме периода (сумма
            requests_finished / длительность).
          </div>
        </div>
      </div>
    </div>
  );
}
