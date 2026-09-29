"use client";

import UPlotChart, { type ChartSeries } from "@/components/charts/UPlotChart";
import { PALETTE, costUrl, useNow, usePoll } from "@/lib/api";
import {
  fmtMillions,
  fmtMoney,
  fmtW,
} from "@/lib/format";
import { usePeriod } from "@/lib/periods";
import type { CostData, CostDayPoint } from "@/lib/types";
import {
  ChartCard,
  ErrorBanner,
  InfoBanner,
  KpiCard,
  LegendChips,
  NoData,
  SkeletonChart,
  SkeletonKpi,
} from "../common";
import { RatesForm } from "./rates-form";

const DAY_S = 86_400;

/** Точки [ts, v] из суточных значений: null/0 — разрыв (пропуски не рисуются как 0). */
function dayPoints(
  days: CostDayPoint[],
  key: "tokens" | "electricity" | "total" | "kwh" | "avg_power_w",
): [number, number | null][] {
  return days.map((d) => [d.day, d[key] === 0 ? null : d[key]]);
}

/**
 * Вкладка «Стоимость» (ТЗ §5.5): Live — окно «сегодня» (00:00 UTC) с опросом
 * каждые 30 с; период — /api/cost?from&to + 30-дневный тренд.
 */
export function CostTab() {
  const { period, from: pFrom, to: pTo } = usePeriod();
  const isLive = period === "live";
  const now = useNow(isLive ? 30_000 : 3_600_000);
  const dayStart = Math.floor(now / DAY_S) * DAY_S;

  const from = isLive || pFrom == null ? dayStart : pFrom;
  const to = isLive || pTo == null ? now : pTo;
  const rangeOk = to > from;
  const url = rangeOk ? costUrl(from, to) : null;
  const { data, loading, error } = usePoll<CostData>(url, isLive ? 30_000 : 0);

  // 30-дневное окно: KPI «за 30 дней» + тренд/графики по дням.
  // now округлён вниз до 5-минутной границы: URL меняется 1 раз в 5 мин,
  // а не на каждом 30-с тике (тяжёлый запрос не переспрашивается зря).
  const monthNow = Math.floor(now / 300) * 300;
  const month = usePoll<CostData>(costUrl(monthNow - 30 * DAY_S, monthNow), 5 * 60_000);
  const m = month.data;

  const cur = data?.currency ?? m?.currency ?? "USD";

  // Средний/медианный день и прогноз на месяц — по дням с данными за 30д
  const dayTotals = (m?.by_day ?? []).map((d) => d.total).sort((a, b) => a - b);
  const nDays = dayTotals.length;
  const avgDay = m != null && nDays > 0 ? m.total / nDays : null;
  const medDay =
    m != null && nDays > 0
      ? nDays % 2
        ? dayTotals[(nDays - 1) / 2]
        : (dayTotals[nDays / 2 - 1] + dayTotals[nDays / 2]) / 2
      : null;

  return (
    <div className="space-y-3">
      {!rangeOk && (
        <InfoBanner message="Период не задан — выберите диапазон в переключателе периода." />
      )}
      {error != null && <ErrorBanner message={error} />}
      {month.error != null && !month.loading && (
        <ErrorBanner message={`30 дней: ${month.error}`} />
      )}

      {loading && !data ? (
        <>
          <SkeletonKpi rows={5} />
          <div className="grid gap-3 xl:grid-cols-2">
            <SkeletonChart />
            <SkeletonChart />
          </div>
        </>
      ) : data != null ? (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            {/* Стоимость за период + stacked-разбивка токены/электричество */}
            <KpiCard
              label={isLive ? "Стоимость сегодня" : "Стоимость за период"}
              className="xl:col-span-2"
              value={
                <span className="text-2xl font-semibold tracking-tight">
                  {fmtMoney(data.total, cur)}
                </span>
              }
              sub={
                <>
                  токены {fmtMoney(data.tokens_cost, cur)} · электричество{" "}
                  {fmtMoney(data.elec_cost, cur)}
                  {isLive && <span> · день — с 00:00 UTC</span>}
                </>
              }
            >
              <BreakdownBar tokens={data.tokens_cost} elec={data.elec_cost} currency={cur} />
            </KpiCard>

            {/* 30 дней + тренд */}
            <KpiCard
              label="Стоимость за 30 дней"
              value={
                m != null ? (
                  fmtMoney(m.total, cur)
                ) : (
                  <span className="inline-block h-6 w-24 animate-pulse rounded bg-panel2" />
                )
              }
              sub={
                m != null ? (
                  <>
                    токены {fmtMoney(m.tokens_cost, cur)} · эл.{" "}
                    {fmtMoney(m.elec_cost, cur)}
                  </>
                ) : undefined
              }
            >
            </KpiCard>

            {/* Средний день + прогноз на месяц */}
            <KpiCard
              label="Средний день"
              value={avgDay != null ? fmtMoney(avgDay, cur) : "—"}
              sub={medDay != null ? `медианный день: ${fmtMoney(medDay, cur)} · дней с данными: ${nDays}` : undefined}
            />
            <KpiCard
              label="Прогноз на месяц"
              value={avgDay != null ? fmtMoney(avgDay * 30, cur) : "—"}
              sub={`средний день × 30 (по ${nDays} дн. данных)`}
            />

            <KpiCard
              label="Prompt-токены (стоимость)"
              value={fmtMoney(data.prompt_tokens_cost, cur)}
              sub={`${data.prompt_tokens > 0 ? fmtMillions(data.prompt_tokens) : "—"} tok по тарифу`}
            />

            <KpiCard
              label="Completion-токены (стоимость)"
              value={fmtMoney(data.completion_tokens_cost, cur)}
              sub={`${data.completion_tokens > 0 ? fmtMillions(data.completion_tokens) : "—"} tok по тарифу`}
            />

            <KpiCard
              label="На запрос (avg)"
              value={fmtMoney(data.per_request, cur)}
              sub={`запросов: ${data.requests}`}
            />
          </div>

          {/* кВт·ч + средняя мощность (полноширинная строка) */}
          <KpiCard
            label="Энергопотребление за период"
            className="md:col-span-2 xl:col-span-4"
            value={
              <>
                <span className="mr-4">{data.kwh.toFixed(2)} кВт·ч</span>
                <span className="text-base text-muted">
                  средняя мощность: {fmtW(data.avg_power_w)}
                </span>
              </>
            }
            sub={`prompt ${fmtMillions(data.prompt_tokens)} · completion ${fmtMillions(data.completion_tokens)}`}
          />

          {data.total === 0 && data.by_day.length === 0 && (
            <InfoBanner message="Нет данных за период — источники не собирались или период пуст." />
          )}

          <div className="grid gap-3 xl:grid-cols-2">
            <ChartCard
              title="Стоимость по дням, 30 дней"
              tip="Стоимость по дням: токены и электричество складываются в столбец (stacked). Дни без данных — разрыв, а не 0."
              legend={
                <LegendChips
                  items={[
                    { name: "токены", color: PALETTE[1] },
                    { name: "электричество", color: PALETTE[0] },
                  ]}
                />
              }
            >
              {(m?.by_day.length ?? 0) === 0 ? (
                <NoData />
              ) : (
                <UPlotChart
                  stack
                  series={[
                    { name: "токены", color: PALETTE[1], points: dayPoints(m!.by_day, "tokens") },
                    {
                      name: "электричество",
                      color: PALETTE[0],
                      points: dayPoints(m!.by_day, "electricity"),
                    },
                  ]}
                />
              )}
            </ChartCard>

            <ChartCard
              title="Средняя мощность по дням, 30 дней (к платёжке)"
              tip="Средняя за день мощность всего сервера, Вт. Завершённые дни — по полным суткам, текущий день — по времени под нагрузкой. Показывает ориентир для сверки с электроплатёжкой."
              note="завершённые дни — по суткам, текущий — по времени под нагрузкой"
            >
              {(m?.power_by_day.length ?? 0) === 0 ? (
                <NoData />
              ) : (
                <UPlotChart
                  series={[
                    {
                      name: "мощность, Вт",
                      color: PALETTE[2],
                      points: m!.power_by_day.map((d) => [d.day, d.avg_power_w]),
                    },
                  ]}
                />
              )}
            </ChartCard>

            <ChartCard
              title="Накопительная стоимость за период"
              tip="Накопленная стоимость (токены + электричество) от начала выбранного периода; последний снимок — итоговая сумма. Значение тарифа — действующий на каждый час."
              className="xl:col-span-2"
              legend={<LegendChips items={[{ name: "накопительно", color: PALETTE[0] }]} />}
            >
              {data.cumulative.length === 0 ? (
                <NoData />
              ) : (
                <UPlotChart series={[{ name: "накопительно", color: PALETTE[0], points: data.cumulative }]} />
              )}
            </ChartCard>
          </div>
        </>
      ) : !error ? (
        <InfoBanner message="Нет данных за период." />
      ) : null}

      {/* Тарифы — общий компонент (дублируется в «Настройках») */}
      <div className="rounded-xl border border-line bg-panel p-4">
        <div className="mb-3 text-sm font-medium">Тарифы</div>
        <RatesForm />
      </div>
    </div>
  );
}

/** Stacked-бар разбивки токены/электричество (простые div-полосы). */
function BreakdownBar({ tokens, elec, currency }: { tokens: number; elec: number; currency: string }) {
  const total = tokens + elec;
  if (total <= 0) return <div className="mt-2 h-1.5 rounded bg-panel2" />;
  const tp = (tokens / total) * 100;
  return (
    <div
      className="mt-2 flex h-1.5 overflow-hidden rounded bg-panel2"
      title={`токены ${fmtMoney(tokens, currency)} · электричество ${fmtMoney(elec, currency)}`}
    >
      <div
        style={{ width: `${tp}%`, backgroundColor: PALETTE[1] }}
        aria-label="токены"
      />
      <div
        style={{ width: `${100 - tp}%`, backgroundColor: PALETTE[0] }}
        aria-label="электричество"
      />
    </div>
  );
}
