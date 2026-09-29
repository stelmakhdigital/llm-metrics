"use client";

import { Progress } from "@/components/ui/progress";
import type { ModelKpi } from "@/lib/api";
import {
  fmtInt,
  fmtLatency,
  fmtPct,
  fmtRatio,
  fmtTokS,
} from "@/lib/format";
import { KpiCard } from "../common";

export interface KpiDef {
  label: string;
  value: string;
  sub?: string;
  /** 0..100 — рисует progress-бар (KV cache) */
  progress?: number | null;
}

/** Сетка KPI-карточек вкладки «Модель» (live или период). */
export function KpiGrid({ cards }: { cards: KpiDef[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {cards.map((c) => (
        <KpiCard key={c.label} label={c.label} value={c.value} sub={c.sub}>
          {c.progress != null && (
            <Progress
              size="sm"
              value={c.progress}
              className="mt-2"
              indicatorClassName={c.progress >= 85 ? "bg-red-500" : "bg-accent"}
            />
          )}
        </KpiCard>
      ))}
    </div>
  );
}

/**
 * Ключи live-KPI — строго из контракта SSE (docs/api-contracts.md):
 * running, waiting, prompt_rate, gen_rate, kv_cache, prefix_hit_rate,
 * ttft_p95, tpot_p95, e2e_p95, preemptions_rate. p50 — из /api/model за 5м.
 */
export function liveKpiCards(
  kpi: Record<string, number | null> | null,
  p50: { ttft: number | null; tpot: number | null } | null,
): KpiDef[] {
  const g = (key: string): number | null =>
    kpi && kpi[key] != null ? (kpi[key] as number) : null;
  return [
    { label: "Running requests", value: fmtInt(g("running")) },
    { label: "Waiting requests", value: fmtInt(g("waiting")) },
    { label: "Токены prompt/s (60 с)", value: fmtTokS(g("prompt_rate")) },
    { label: "Токены generation/s (60 с)", value: fmtTokS(g("gen_rate")) },
    {
      label: "TTFT p95",
      value: fmtLatency(g("ttft_p95")),
      sub: `p50: ${fmtLatency(p50?.ttft ?? null)}`,
    },
    {
      label: "TPOT p95",
      value: fmtLatency(g("tpot_p95")),
      sub: `p50: ${fmtLatency(p50?.tpot ?? null)}`,
    },
    { label: "E2E p95", value: fmtLatency(g("e2e_p95")) },
    { label: "KV cache", value: fmtPct(g("kv_cache")), progress: g("kv_cache") },
    { label: "Prefix cache hit rate", value: fmtRatio(g("prefix_hit_rate")) },
    {
      label: "Preemptions/s",
      value: g("preemptions_rate") == null ? "—" : g("preemptions_rate")!.toFixed(3),
    },
  ];
}

/** KPI за период: running/waiting — последние, rates — средние, счётчики — суммы. */
export function periodKpiCards(kpi: ModelKpi, spanSec: number): KpiDef[] {
  const reqRate =
    kpi.requests_finished != null && spanSec > 0
      ? kpi.requests_finished / spanSec
      : null;
  return [
    { label: "Running requests (последние)", value: fmtInt(kpi.running) },
    { label: "Waiting requests (последние)", value: fmtInt(kpi.waiting) },
    { label: "Запросы/с (средние)", value: reqRate == null ? "—" : reqRate.toFixed(2) },
    { label: "Токены prompt/s (средние)", value: fmtTokS(kpi.prompt_rate) },
    { label: "Токены generation/s (средние)", value: fmtTokS(kpi.gen_rate) },
    {
      label: "TTFT p50 / p95",
      value: fmtLatency(kpi.ttft_p95),
      sub: `p50: ${fmtLatency(kpi.ttft_p50)}`,
    },
    {
      label: "TPOT p50 / p95",
      value: fmtLatency(kpi.tpot_p95),
      sub: `p50: ${fmtLatency(kpi.tpot_p50)}`,
    },
    { label: "E2E p95", value: fmtLatency(kpi.e2e_p95) },
    { label: "KV cache (последнее)", value: fmtPct(kpi.kv_cache), progress: kpi.kv_cache },
    { label: "Prefix cache hit rate", value: fmtRatio(kpi.prefix_hit_rate) },
    { label: "Preemptions (сумма)", value: fmtInt(kpi.preemptions) },
    { label: "Завершено запросов (сумма)", value: fmtInt(kpi.requests_finished) },
  ];
}
