"use client";

import type { ChartMark } from "@/components/charts/marked-uplot";
import { usePeriod } from "@/lib/periods";
import { useModel } from "@/lib/model-context";
import {
  modelUrl,
  PALETTE,
  usePoll,
  type ModelData,
  type ModelSegment,
} from "@/lib/api";
import { ErrorBanner, InfoBanner, NoData, SkeletonKpi, SkeletonChart } from "../common";
import { MetricChart, type MetricSpec } from "../metric-chart";
import { TokenDistributions } from "./distributions";
import { FinishReasons } from "./finish-reasons";
import { KpiGrid, periodKpiCards } from "./kpi";
import { ModelBadges } from "./model-badges";

// ------------------------------------------------------------------- specs

const TTFT_SPECS: MetricSpec[] = [
  { metric: "ttft_p50", label: "p50", color: PALETTE[1] },
  { metric: "ttft_p95", label: "p95", color: PALETTE[0] },
];

const ITL_TPOT_SPECS: MetricSpec[] = [
  { metric: "itl_p50", label: "ITL p50", color: PALETTE[1] },
  { metric: "itl_p95", label: "ITL p95", color: PALETTE[0] },
  { metric: "tpot_p50", label: "TPOT p50", color: PALETTE[3] },
  { metric: "tpot_p95", label: "TPOT p95", color: PALETTE[6] },
];

const E2E_SPECS: MetricSpec[] = [{ metric: "e2e_latency_p95", label: "p95", color: PALETTE[0] }];

const THROUGHPUT_SPECS: MetricSpec[] = [
  { metric: "prompt_tokens_rate", label: "prompt tok/s", color: PALETTE[1] },
  { metric: "generation_tokens_rate", label: "generation tok/s", color: PALETTE[0] },
];

const KV_SPECS: MetricSpec[] = [{ metric: "kv_cache_usage", label: "KV cache", color: PALETTE[2] }];
const QUEUE_SPECS: MetricSpec[] = [
  { metric: "num_requests_running", label: "running", color: PALETTE[3] },
  { metric: "num_requests_waiting", label: "waiting", color: PALETTE[4] },
];
const PREFIX_SPECS: MetricSpec[] = [
  { metric: "prefix_hit_rate", label: "hit rate", color: PALETTE[3] },
];

/** Границы сегментов модели → вертикальные линии на графиках. */
function modelMarks(models: ModelSegment[]): ChartMark[] {
  if (models.length < 2) return [];
  return models.slice(1).map((m) => ({ ts: m.from, label: m.name }));
}

// ------------------------------------------------------------------- page

/**
 * Вкладка «Модель» в режиме периода: GET /api/model?from&to (KPI, модели,
 * distributions) + графики через /api/metrics/{metric}?from&to.
 */
export function ModelPeriod() {
  const { period, from, to } = usePeriod();
  const { model } = useModel();
  const rangeOk = from != null && to != null && to > from;
  const url = rangeOk ? modelUrl(from, to, model) : null;
  const { data, loading, error } = usePoll<ModelData>(url, 0);

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

  const spanSec = (to as number) - (from as number);
  const marks = modelMarks(data?.models ?? []);
  const kpi = data?.kpi ?? null;

  return (
    <div className="space-y-3">
      {error != null && <ErrorBanner message={error} />}

      {loading && !data ? (
        <SkeletonKpi rows={8} />
      ) : (
        <>
          {data?.models.length != null && data.models.length > 0 && (
            <ModelBadges models={data.models} />
          )}

          {model != null && (
            <InfoBanner
              message={`Фильтр по модели «${model}»: показаны только данные этой модели (≤24ч — сырые, дальше — hourly-агрегаты; счётчики/финиш-причины — в пределах 168 ч).`}
            />
          )}

          {kpi != null ? (
            <KpiGrid cards={periodKpiCards(kpi, spanSec)} />
          ) : !error ? (
            <NoData />
          ) : null}
        </>
      )}

      {loading && !data ? (
        <div className="grid gap-3 xl:grid-cols-2">
          <SkeletonChart />
          <SkeletonChart />
        </div>
      ) : (
        <>
          <div className="grid gap-3 lg:grid-cols-3">
            <TokenDistributions distributions={data?.distributions ?? null} className="lg:col-span-2" />
            <FinishReasons reasons={kpi?.finish_reasons ?? null} />
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            <MetricChart
              title="TTFT — время до первого токена, с"
              specs={TTFT_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Время от поступления запроса до первого токена ответа (p50/p95). Квантили из кумулятивного histogram'а vLLM: отражают статистику с момента запуска/рестарта vLLM, не только выбранный период."
            />
            <MetricChart
              title="ITL / TPOT, с"
              specs={ITL_TPOT_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="ITL — пауза между последовательными токенами, TPOT — среднее время на один сгенерированный токен (p50/p95). Квантили из кумулятивного histogram'а vLLM (с момента запуска/рестарта)."
            />
            <MetricChart
              title="E2E latency p95, с"
              specs={E2E_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Полное время запроса: от поступления до последнего токена, p95. Квантиль из кумулятивного histogram'а vLLM; растёт с длиной генерации."
            />
            <MetricChart
              title="Throughput, токены/с"
              specs={THROUGHPUT_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Скорость обработки токенов: prompt (вход, включает токены из prefix-кэша — поэтому может быть много выше, чем «Avg prompt throughput» в логах vLLM) и generation (выход)."
            />
            <MetricChart
              title="KV cache usage"
              specs={KV_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Занятость KV-кэша vLLM, % (мемори под ключи/значения attention). Высокая близкая к 100% — новые запросы могут не помещаться и вытеснять старые (премпты)."
            />
            <MetricChart
              title="Запросы: running / waiting"
              specs={QUEUE_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Сколько запросов сейчас в работе (running) и сколько ждёт в очереди (waiting). 0 в очереди — все поступающие запросы сразу уходят в работу."
            />
            <MetricChart
              title="Prefix cache hit rate"
              specs={PREFIX_SPECS}
              from={from as number}
              to={to as number}
              marks={marks}
              model={model}
              tip="Доля prompt-токенов, найденных в prefix-кэше (hits/queries). Чем выше — тем больше запросов не пересчитывают общую часть промпта."
            />
          </div>
        </>
      )}
    </div>
  );
}
