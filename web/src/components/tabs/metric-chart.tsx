"use client";

import { useEffect, useState } from "react";
import { Download, FileImage } from "lucide-react";
import UPlotChart, { type ChartSeries } from "@/components/charts/UPlotChart";
import MarkedUPlot, { type ChartMark } from "@/components/charts/marked-uplot";
import { fetchJson, metricUrl, type MetricResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
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

// ------------------------------------------------------------------- export

function download(name: string, url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
}

function exportCsv(series: ChartSeries[], from: number, to: number, title: string) {
  // объединённый таймлайн (как в uPlot)
  const tsSet = new Set<number>();
  for (const s of series) for (const [ts] of s.points) tsSet.add(ts);
  const xs = [...tsSet].sort((a, b) => a - b);
  const byTs = series.map((s) => new Map<number, number | null>(s.points));
  const head = ["time", ...series.map((s) => s.name)].join(",");
  const rows = xs.map((ts) => {
    const cells = [
      new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 19) + " UTC",
      ...byTs.map((m) => {
        const v = m.get(ts);
        return v == null ? "" : String(v);
      }),
    ];
    return cells.join(",");
  });
  // BOM — чтобы Excel корректно открыл UTF-8
  const blob = new Blob(["\uFEFF" + [head, ...rows].join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  download(`${title}-${from}-${to}.csv`, url);
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * PNG-снимок графика (F4.2): локальный рендер серий на canvas
 * (установленная сборка uPlot 1.6.32 не экспортирует toDataURL).
 * Тёмная тема, время в локальных часах сервера.
 */
function exportPng(series: ChartSeries[], from: number, to: number, title: string, height = 360) {
  const width = 1000;
  const pad = { l: 52, r: 12, t: 12, b: 26 };
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;

  const canvas = document.createElement("canvas");
  const px = window.devicePixelRatio || 1;
  canvas.width = width * px;
  canvas.height = height * px;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(px, px);

  ctx.fillStyle = "#101014";
  ctx.fillRect(0, 0, width, height);

  const spanX = Math.max(1, to - from);
  const x = (ts: number) => pad.l + ((ts - from) / spanX) * plotW;
  // авто-масштаб Y по максимуму видимых значений (nice-округление)
  let maxV = 0;
  for (const s of series)
    for (const [ts, v] of s.points)
      if (v != null && ts >= from && ts <= to) maxV = Math.max(maxV, v);
  const spanY = niceCeil(maxV);
  const y = (v: number) => pad.t + plotH - (spanY > 0 ? (Math.max(0, v) / spanY) * plotH : 0);

  ctx.strokeStyle = "#2a2a31";
  ctx.lineWidth = 1;
  ctx.font = "12px system-ui";
  ctx.fillStyle = "#8b8b93";

  // сетка Y: 5 делений
  for (let i = 0; i <= 4; i++) {
    const v = (spanY / 4) * i;
    const yy = y(v);
    ctx.beginPath();
    ctx.moveTo(pad.l, yy);
    ctx.lineTo(width - pad.r, yy);
    ctx.stroke();
    ctx.fillText(v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Number.isInteger(v) ? String(v) : v.toFixed(1), 4, yy + 4);
  }
  // сетка X: 6 делений, подписи — «дд.мм чч:мм»
  for (let i = 0; i <= 5; i++) {
    const ts = from + (spanX / 5) * i;
    const xx = x(ts);
    ctx.beginPath();
    ctx.moveTo(xx, pad.t);
    ctx.lineTo(xx, height - pad.b);
    ctx.stroke();
    const d = new Date(ts * 1000);
    const lbl = `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    ctx.fillText(lbl, Math.min(xx, width - 90), height - 8);
  }

  // заголовок
  ctx.fillStyle = "#e5e5ea";
  ctx.font = "13px system-ui";
  ctx.fillText(title, pad.l, height - pad.b - 6);

  // серии
  for (const s of series) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let pen = false;
    for (const [ts, v] of s.points) {
      if (v == null || ts < from || ts > to) {
        pen = false;
        continue;
      }
      const xx = x(ts);
      const yy = y(Math.max(0, Math.min(v, spanY)));
      if (!pen) {
        ctx.moveTo(xx, yy);
        pen = true;
      } else {
        ctx.lineTo(xx, yy);
      }
    }
    ctx.stroke();
  }

  try {
    download(`${title}-${from}-${to}.png`, canvas.toDataURL("image/png"));
  } catch {
    /* canvas недоступен — молча пропускаем */
  }
}

/** max → nice-округление сверху (1/2/5·10ⁿ); 0 → 1. */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

// ------------------------------------------------------------------- chart

/**
 * Карточка-график периода: N серий из /api/metrics/{metric}?from&to[&model],
 * легенда, состояния (skeleton / нет данных / ошибка), опциональные
 * вертикальные оранжевые линии на границах сегментов модели (marks),
 * экспорт CSV/PNG (F4.2).
 */
export function MetricChart({
  title,
  specs,
  from,
  to,
  marks,
  note,
  tip,
  height = 220,
  model,
}: {
  title: string;
  specs: MetricSpec[];
  from: number;
  to: number;
  marks?: ChartMark[];
  note?: React.ReactNode;
  /** Пояснение к графику — иконка «?» у заголовка */
  tip?: string;
  height?: number;
  /** F4.4: фильтр по модели (только вкладки vLLM) */
  model?: string | null;
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
      specs.map((s) => fetchJson<MetricResponse>(metricUrl(s.metric, from, to, model))),
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
  }, [key, from, to, model]);

  const marksList = marks ?? [];
  const hasData = state.hasData;
  return (
    <ChartCard
      title={title}
      note={note}
      tip={tip}
      legend={
        <LegendChips items={specs.map((s) => ({ name: s.label, color: s.color }))} />
      }
      actions={
        hasData ? (
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="icon"
              className="size-7 text-muted hover:text-foreground"
              title="Экспорт CSV"
              onClick={() => exportCsv(state.series, from, to, title)}
            >
              <Download className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 text-muted hover:text-foreground"
              title="Экспорт PNG"
              onClick={() => exportPng(state.series, from, to, title)}
            >
              <FileImage className="size-3.5" />
            </Button>
          </div>
        ) : undefined
      }
    >
      {state.error && <ErrorBanner message={state.error} />}
      {state.loading && !state.error ? (
        <SkeletonChart height={height - 48} />
      ) : !hasData ? (
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
