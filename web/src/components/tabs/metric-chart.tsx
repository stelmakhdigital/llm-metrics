"use client";

import { useEffect, useState } from "react";
import UPlotChart, { type ChartSeries } from "@/components/charts/UPlotChart";
import MarkedUPlot, { type ChartMark } from "@/components/charts/marked-uplot";
import { fetchJson, metricUrl, type MetricResponse } from "@/lib/api";
import { ChartCard, ErrorBanner, LegendChips, NoData, SkeletonChart } from "./common";

export interface MetricSpec {
  /** имя метрики в БД (GET /api/metrics/{metric}) */
  metric: string;
  label: string;
  color: string;
}

interface State {
  series: ChartSeries[];
  loading: boolean;
  error: string | null;
  /** есть хотя бы одна точка хотя бы в одной серии */
  hasData: boolean;
}

function toSeries(specs: MetricSpec[], responses: MetricResponse[]): ChartSeries[] {
  return specs.map((s, i) => ({
    name: s.label,
    color: s.color,
    points: (responses[i]?.points ?? []) as [number, number | null][],
  }));
}

/**
 * Карточка-график периода: N серий из /api/metrics/{metric}?from&to,
 * легенда, состояния (skeleton / нет данных / ошибка), опциональные
 * вертикальные оранжевые линии на границах сегментов модели (marks).
 */
export function MetricChart({
  title,
  specs,
  from,
  to,
  marks,
  note,
  height = 220,
}: {
  title: string;
  specs: MetricSpec[];
  from: number;
  to: number;
  marks?: ChartMark[];
  note?: React.ReactNode;
  height?: number;
}) {
  const [state, setState] = useState<State>({
    series: specs.map((s) => ({ name: s.label, color: s.color, points: [] })),
    loading: true,
    error: null,
    hasData: false,
  });

  // specs — константы модуля, передаются стабильно; key — на случай динамических списков
  const key = specs.map((s) => s.metric).join(",");
  useEffect(() => {
    let cancelled = false;
    setState({
      series: specs.map((s) => ({ name: s.label, color: s.color, points: [] })),
      loading: true,
      error: null,
      hasData: false,
    });
    Promise.all(
      specs.map((s) => fetchJson<MetricResponse>(metricUrl(s.metric, from, to))),
    )
      .then((responses) => {
        if (cancelled) return;
        const series = toSeries(specs, responses);
        setState({
          series,
          loading: false,
          error: null,
          hasData: series.some((s) => s.points.length > 0),
        });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState((st) => ({
          ...st,
          loading: false,
          error: e instanceof Error ? e.message : "Ошибка API",
        }));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, from, to]);

  const marksList = marks ?? [];
  return (
    <ChartCard
      title={title}
      note={note}
      legend={
        <LegendChips items={specs.map((s) => ({ name: s.label, color: s.color }))} />
      }
    >
      {state.error && <ErrorBanner message={state.error} />}
      {state.loading && !state.error ? (
        <SkeletonChart height={height - 48} />
      ) : !state.hasData ? (
        <NoData />
      ) : (
        marksList.length > 0 ? (
          <MarkedUPlot series={state.series} height={height} marks={marksList} />
        ) : (
          <UPlotChart series={state.series} height={height} />
        )
      )}
    </ChartCard>
  );
}
