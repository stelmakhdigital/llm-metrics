"use client";

import { useMemo } from "react";
import Link from "next/link";
import {
  ALERTS_URL,
  HEALTH_URL,
  OVERVIEW_URL,
  costUrl,
  modelUrl,
  useNow,
  usePoll,
  type AlertsData,
  type HealthInfo,
  type ModelData,
  type OverviewSnapshot,
} from "@/lib/api";
import type { CostData } from "@/lib/types";
import {
  NA,
  fmtAgo,
  fmtInt,
  fmtLatency,
  fmtMillions,
  fmtMiB,
  fmtMoney,
  fmtPct,
  fmtTokS,
  fmtW,
} from "@/lib/format";
import {
  ChartCard,
  ErrorBanner,
  KpiCard,
  NoData,
  SkeletonKpi,
} from "../common";
import { cn } from "@/lib/utils";

const DAY_S = 86_400;
/** Точка статуса стека (перечень фиксирован — основные источники). */
const SOURCE_CHIPS: { key: string; label: string }[] = [
  { key: "vllm", label: "vLLM" },
  { key: "gpu", label: "GPU" },
  { key: "system", label: "SYS" },
];

function StatusDot({ status }: { status: string }) {
  const color =
    status === "online"
      ? "bg-emerald-400"
      : status === "offline"
        ? "bg-red-400"
        : "bg-muted/50";
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", color)} aria-hidden />;
}

/**
 * Вкладка «Сводка» — главная страница: статус стека, KPI текущей модели за 24ч,
 * GPU (суммарно), стоимость 24ч/7д, активные алерты. Только существующие API.
 */
export function OverviewTab() {
  // now тикает раз в минуту — окно 24ч смещается; тяжёлый 7д-запрос по
  // 5-минутной границе (как 30-дневное окно вкладки «Стоимость»).
  const now = useNow(60_000);
  const dayAgo = now - DAY_S;
  const weekTo = Math.floor(now / 300) * 300;

  // API — одноресурсный (SQLite + Python на CPU, занятом vLLM): параллельные
  // тяжёлые запросы упираются в 30s-таймаут прокси (500). Тяжёлые гранируем:
  // model → overview → cost24 → cost7, по одному. Лёгкие (health, alerts) — сразу.
  // (один активный model-деплой: /api/model без фильтра = KPI текущей модели)
  const model = usePoll<ModelData>(modelUrl(dayAgo, now), 60_000);
  const modelDone = model.data != null || model.error != null;

  const overview = usePoll<OverviewSnapshot>(modelDone ? OVERVIEW_URL : null, 30_000);
  const ovDone = overview.data != null || overview.error != null;

  const cost24 = usePoll<CostData>(ovDone ? costUrl(dayAgo, now) : null, 60_000);
  const c24Done = cost24.data != null || cost24.error != null;

  const cost7 = usePoll<CostData>(c24Done ? costUrl(weekTo - 7 * DAY_S, weekTo) : null, 5 * 60_000);

  const health = usePoll<HealthInfo>(HEALTH_URL, 30_000);
  const alerts = usePoll<AlertsData>(ALERTS_URL, 30_000);

  // --- статус стека: предпочитаем детальный /api/health, fallback — overview
  const sources = health.data?.sources ?? overview.data?.sources ?? {};

  // --- KPI модели. Токены за 24ч — сумма счётчиков из /api/cost (в /api/model
  //  только гистограммы-бакеты, не суммарный счётчик).
  const kpi = model.data?.kpi ?? null;
  const modelName = overview.data?.model ?? null;
  const tokens24 = cost24.data
    ? cost24.data.prompt_tokens + cost24.data.completion_tokens
    : null;

  // --- GPU (суммарно по снимку overview)
  const ov = overview.data;
  const gpuUtil = useMemo(() => {
    const us = (ov?.gpus ?? [])
      .map((g) => g.util_pct)
      .filter((v): v is number => v != null);
    return us.length ? us.reduce((s, v) => s + v, 0) / us.length : null;
  }, [ov]);
  const gpuMemPct =
    ov && ov.total_mem_mib ? (ov.total_mem_used_mib ?? 0) / ov.total_mem_mib * 100 : null;

  // --- алерты: последние срабатывания, новые сверху
  const activeCount = alerts.data?.active.length ?? 0;
  const recent = (alerts.data?.recent ?? []).slice(0, 5);

  const anyError =
    [overview, health, model, cost24, cost7, alerts]
      .map((p) => p.error)
      .filter(Boolean).length;

  return (
    <div className="space-y-3">
      {anyError > 0 && (
        <ErrorBanner
          message={
            [overview, health, model, cost24, cost7, alerts]
              .map((p) => p.error)
              .filter(Boolean)
              .join(" · ")
          }
        />
      )}

      {/* Статус стека */}
      <section className="rounded-xl border border-line bg-panel p-3">
        <h2 className="mb-2 text-sm font-medium">Статус стека</h2>
        {!health.data && !overview.data && !health.error ? (
          <div className="flex gap-2">
            {SOURCE_CHIPS.map((c) => (
              <div key={c.key} className="h-8 w-28 animate-pulse rounded-lg bg-panel2" />
            ))}
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {SOURCE_CHIPS.map(({ key, label }) => {
              const s = sources[key];
              const status = s?.status ?? "unknown";
              return (
                <div
                  key={key}
                  className="flex items-center gap-2 rounded-lg border border-line bg-panel2/40 px-2.5 py-1.5 text-sm"
                >
                  <StatusDot status={status} />
                  <span>{label}</span>
                  <span className="text-xs text-muted">
                    {status === "online"
                      ? fmtAgo(s?.last_ok_ts ?? null)
                      : status === "offline"
                        ? "оффлайн"
                        : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* KPI текущей модели за 24ч */}
      <section>
        <h2 className="mb-2 flex items-baseline gap-2 text-sm font-medium">
          <span>Модель — за 24ч</span>
          {modelName && <span className="truncate text-xs text-muted">{modelName}</span>}
        </h2>
        {model.loading && !model.data ? (
          <SkeletonKpi rows={6} />
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <KpiCard label="Запросы" value={kpi ? fmtInt(kpi.requests_finished) : NA} />
            <KpiCard
              label="Токены"
              value={tokens24 != null ? fmtMillions(tokens24) : NA}
              sub={tokens24 != null ? `всего за сутки` : undefined}
            />
            <KpiCard label="TTFT p95" value={kpi ? fmtLatency(kpi.ttft_p95) : NA} />
            <KpiCard label="E2E p95" value={kpi ? fmtLatency(kpi.e2e_p95) : NA} />
            <KpiCard label="Генерация" value={kpi ? fmtTokS(kpi.gen_rate) : NA} />
            <KpiCard
              label="KV-кэш"
              value={kpi ? fmtPct(kpi.kv_cache) : NA}
              sub={kpi ? `running ${fmtInt(kpi.running)} · waiting ${fmtInt(kpi.waiting)}` : undefined}
            />
          </div>
        )}
      </section>

      {/* GPU / Стоимость / Алерты */}
      <div className="grid gap-3 lg:grid-cols-3">
        {/* GPU — суммарно */}
        <ChartCard title="GPU — суммарно" tip="Сумма/среднее по всем GPU из последнего снимка поллера.">
          {ov ? (
            <>
              <div className="space-y-1 text-sm">
                <Row label="Мощность" value={fmtW(ov.total_power_w)} />
                <Row label="Загрузка" value={gpuUtil != null ? fmtPct(gpuUtil) : NA} />
                <Row
                  label="Память"
                  value={
                    ov.total_mem_used_mib != null
                      ? `${fmtMiB(ov.total_mem_used_mib)} / ${fmtMiB(ov.total_mem_mib)}`
                      : NA
                  }
                  sub={gpuMemPct != null ? fmtPct(gpuMemPct) : undefined}
                />
              </div>
              {ov.gpus.length === 0 ? (
                <NoData text="Нет данных (GPU оффлайн?)" />
              ) : (
                <div className="mt-2 text-xs text-muted">GPU: {ov.gpus.length}</div>
              )}
            </>
          ) : ovDone ? (
            <NoData text="Нет данных (GPU оффлайн?)" />
          ) : (
            <NoData text="Загрузка…" />
          )}
        </ChartCard>

        {/* Стоимость */}
        <ChartCard title="Стоимость" tip="Расчёт по тарифам: токены + электричество. Окна 24ч и 7д.">
          <div className="space-y-1 text-sm">
            <Row
              label="За 24ч"
              value={cost24.data ? fmtMoney(cost24.data.total, cost24.data.currency) : NA}
              sub={
                cost24.data
                  ? `токены ${fmtMoney(cost24.data.tokens_cost, cost24.data.currency)} · эл. ${fmtMoney(cost24.data.elec_cost, cost24.data.currency)}`
                  : undefined
              }
            />
            <Row
              label="За 7д"
              value={cost7.data ? fmtMoney(cost7.data.total, cost7.data.currency) : NA}
              sub={
                cost7.data
                  ? `токены ${fmtMoney(cost7.data.tokens_cost, cost7.data.currency)} · эл. ${fmtMoney(cost7.data.elec_cost, cost7.data.currency)}`
                  : undefined
              }
            />
          </div>
          {!cost24.data && !cost24.error && <NoData text="Загрузка…" />}
          <Link href="/cost" className="mt-2 inline-block text-xs text-accent underline-offset-2 hover:underline">
            Подробнее →
          </Link>
        </ChartCard>

        {/* Алерты */}
        <ChartCard
          title="Алерты"
          tip="Активные алерты и последние срабатывания."
          actions={
            activeCount > 0 ? (
              <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">
                {activeCount} активных
              </span>
            ) : undefined
          }
        >
          {alerts.loading && !alerts.data ? (
            <NoData text="Загрузка…" />
          ) : recent.length === 0 ? (
            <div className="flex h-40 items-center justify-center text-sm text-emerald-400">
              Активных алертов нет
            </div>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {recent.map((a) => (
                <li key={a.id} className="flex items-start gap-2">
                  <span
                    className={cn(
                      "mt-1.5 inline-block size-2 shrink-0 rounded-full",
                      a.status === "active" ? "bg-red-400" : "bg-muted/40",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className={cn(a.status === "active" && "text-red-400")}>{a.rule}</span>{" "}
                    <span className="text-xs text-muted">
                      · {a.level} · {fmtAgo(a.triggered_at)}
                      {a.status === "resolved" && " · снят"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link href="/alerts" className="mt-2 inline-block text-xs text-accent underline-offset-2 hover:underline">
            Все алерты →
          </Link>
        </ChartCard>
      </div>
    </div>
  );
}

/** Строка «метка — значение» внутри блока. */
function Row({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-muted">{label}</span>
      <span className="text-right">
        <span className="font-medium">{value}</span>
        {sub && <span className="ml-2 text-xs text-muted">{sub}</span>}
      </span>
    </div>
  );
}
