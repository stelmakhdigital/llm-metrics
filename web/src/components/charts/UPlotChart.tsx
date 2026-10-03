"use client";

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

export interface ChartSeries {
  name: string;
  color: string;
  /** [epoch-с, значение|null] — null = пропуск (разрыв линии) */
  points: [number, number | null][];
}

export interface UPlotChartProps {
  series: ChartSeries[];
  height?: number;
  /** live-режим: окно за последние ~5 минут, без выбора/перетаскивания */
  live?: boolean;
  /** stacked: серии рисуются областями от 0 (у uPlot нет нативного stack —
      серии перекрываются, fill до нуля) */
  stack?: boolean;
}

/**
 * Базовая обёртка uPlot: общий временной ось по объединению ts всех серий,
 * пропуски (null) рисуются разрывами. Пересоздаёт график при смене данных.
 */
/** Метки оси X: HH:MM на коротких окнах, даты — на длинных (локальное время). */
function fmtAxisTime(ts: number, spanS: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  if (spanS <= 36 * 3600) return `${p(d.getHours())}:${p(d.getMinutes())}`;
  if (spanS <= 14 * 86400)
    return `${p(d.getDate())}.${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}`;
}

export default function UPlotChart({ series, height = 220, live = false, stack = false }: UPlotChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);

  // пустые данные (нет точек или все null) — заглушка, а не пустая сетка с осями
  const hasPoints = series.some((s) => s.points.some(([, v]) => v != null));
  useEffect(() => {
    if (!hostRef.current || series.length === 0 || !hasPoints) return;

    // общий таймлайн: union всех ts, значения серий — с null на пропусках
    const tsSet = new Set<number>();
    for (const s of series) for (const [ts] of s.points) tsSet.add(ts);
    const xs = [...tsSet].sort((a, b) => a - b);

    const values = series.map((s) => {
      const byTs = new Map<number, number | null>(s.points);
      return xs.map((ts) => byTs.get(ts) ?? null);
    });

    const opts: uPlot.Options = {
      width: hostRef.current.clientWidth || 600,
      height,
      series: [
        { label: "" },
        ...series.map((s) => ({
          label: s.name,
          stroke: s.color,
          width: 1.5,
          // у uPlot авто-логика прячет точки на плотных рядах (points.space) —
          // на 1ч/24ч точки пропадали; width — размер, space: 1 — не прятать
          points: { width: 4, space: 1 },
          // min: 0 на y ломает авто-range в uPlot 1.6 (max остаётся null —
          // график пустой), поэтому низ не фиксируем: авто-range и так уходит в 0
          ...(stack ? { fill: "origin" } : {}),
        })),
      ],
      scales: {
        x: {
          time: true,
          // live: окно последних ~5 минут; история: авто-диапазон по данным
          ...(live && xs.length > 0
            ? { auto: false, min: xs[xs.length - 1] - 300, max: xs[xs.length - 1] }
            : { auto: true }),
        },
        y: { auto: true },
      },
      axes: [
        {
          stroke: "#8b8b93",
          size: 36,
          grid: { show: false },
          // дефолтный формат uPlot — англ. 12ч («12pm/4am») — заменяем
          ...(xs.length > 0
            ? { fmtTime: (ts: number) => fmtAxisTime(ts, xs[xs.length - 1] - xs[0]) }
            : {}),
        },
        {
          stroke: "#8b8b93",
          font: "11px system-ui",
          space: 40,
          grid: { stroke: "#1f1f24", width: 1 },
        },
      ],
      cursor: { drag: { x: false, y: false } },
      legend: { show: false },
      // отступы: сверху от заголовка и снизу от текста оси X (симметрично)
      padding: [14, 12, 14, 12],
    };

    const chart = new uPlot(opts, [[...xs], ...values], hostRef.current);
    chartRef.current = chart;
    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, [series, height, live, stack, hasPoints]);

  if (!hasPoints) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-line bg-panel2 text-xs text-muted"
        style={{ height }}
      >
        нет данных
      </div>
    );
  }

  return (
    <div ref={hostRef} className="w-full" style={{ height }} />
  );
}
