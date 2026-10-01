"use client";

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { ChartSeries } from "./UPlotChart";

export interface ChartMark {
  /** момент линии, epoch-с */
  ts: number;
  label?: string;
}

interface MarkedUPlotProps {
  series: ChartSeries[];
  height?: number;
  marks: ChartMark[];
}

/**
 * Локальная обёртка uPlot «под модель»: как базовый UPlotChart, плюс
 * вертикальные оранжевые пунктирные линии на границах сегментов модели
 * (ТЗ §5.2 — отслеживание смены модели). Общий UPlotChart.tsx не меняется —
 * линии рисует uPlot-hook `bind` прямо в plot-области.
 */
export default function MarkedUPlot({ series, height = 220, marks }: MarkedUPlotProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const marksRef = useRef<ChartMark[]>(marks);
  marksRef.current = marks;

  useEffect(() => {
    if (!hostRef.current || series.length === 0) return;

    // общий таймлайн — как в UPlotChart
    const tsSet = new Set<number>();
    for (const s of series) for (const [ts] of s.points) tsSet.add(ts);
    const xs = [...tsSet].sort((a, b) => a - b);
    if (xs.length === 0) return;

    const values = series.map((s) => {
      const byTs = new Map<number, number | null>(s.points);
      return xs.map((ts) => byTs.get(ts) ?? null);
    });

    const drawMarks = (u: uPlot) => {
      const { ctx, bbox } = u;
      if (bbox.width <= 0 || bbox.height <= 0) return;
      ctx.save();
      ctx.strokeStyle = "#f97316";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      for (const m of marksRef.current) {
        const px = bbox.left + u.valToPos(m.ts, "x");
        if (px < bbox.left || px > bbox.left + bbox.width) continue;
        ctx.beginPath();
        ctx.moveTo(px, bbox.top);
        ctx.lineTo(px, bbox.top + bbox.height);
        ctx.stroke();
      }
      ctx.restore();
    };

    const opts: uPlot.Options = {
      width: hostRef.current.clientWidth || 600,
      height,
      series: [
        { label: "" },
        ...series.map((s) => ({
          label: s.name,
          stroke: s.color,
          width: 1.5,
          points: { width: 4 },
        })),
      ],
      scales: { x: { time: true, auto: true }, y: { auto: true } },
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
      // "draw" — после отрисовки всех серий: поверх них линии сегментов
      hooks: { draw: [drawMarks] },
      padding: [8, 8, 0, 0],
    };

    const chart = new uPlot(opts, [[...xs], ...values], hostRef.current);
    return () => {
      chart.destroy();
    };
    // marks — через ref: hook "draw" берёт актуальные значения на каждой перерисовке
  }, [series, height]);

  return <div ref={hostRef} className="w-full" style={{ height }} />;
}
