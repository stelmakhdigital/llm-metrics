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
}

/**
 * Базовая обёртка uPlot: общий временной ось по объединению ts всех серий,
 * пропуски (null) рисуются разрывами. Пересоздаёт график при смене данных.
 */
export default function UPlotChart({ series, height = 220, live = false }: UPlotChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);

  useEffect(() => {
    if (!hostRef.current || series.length === 0) return;

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
        ...series.map((s) => ({ label: s.name, stroke: s.color, width: 1.5 })),
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
        { stroke: "#8b8b93", size: 36, grid: { show: false } },
        {
          stroke: "#8b8b93",
          font: "11px system-ui",
          space: 40,
          grid: { stroke: "#1f1f24", width: 1 },
        },
      ],
      cursor: { drag: { x: false, y: false } },
      legend: { show: false },
      padding: [8, 8, 0, 0],
    };

    const chart = new uPlot(opts, [[...xs], ...values], hostRef.current);
    chartRef.current = chart;
    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, [series, height, live]);

  return (
    <div ref={hostRef} className="w-full" style={{ height }} />
  );
}
