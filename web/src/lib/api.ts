"use client";

import { useCallback, useEffect, useState } from "react";

/** Палитра серий графиков (тёмная тема; accent — оранжевый). */
export const PALETTE = [
  "#f97316",
  "#38bdf8",
  "#34d399",
  "#a78bfa",
  "#f472b6",
  "#facc15",
  "#2dd4bf",
  "#fb7185",
  "#60a5fa",
  "#4ade80",
];

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as Promise<T>;
}

/** PUT с JSON-телом (напр. /api/settings/cost). */
export async function putJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "PUT",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (j && typeof j.detail === "string") detail = j.detail;
      else if (j && typeof j.detail !== "undefined" && j.detail !== null) {
        detail = JSON.stringify(j.detail);
      }
    } catch {
      /* body не JSON — оставляем HTTP-статус */
    }
    throw new Error(detail);
  }
  return (await res.json()) as Promise<T>;
}

/** Точки /api/metrics/{metric}: [[epoch-с, значение|null], ...]. */
export interface MetricResponse {
  metric: string;
  source: string | null;
  count: number;
  points: [number, number | null][];
}

export function metricUrl(
  metric: string,
  from: number,
  to: number,
  model?: string | null,
): string {
  let u = `/api/metrics/${encodeURIComponent(metric)}?from=${from}&to=${to}`;
  if (model) u += `&model=${encodeURIComponent(model)}`;
  return u;
}

// ------------------------------------------------------------------ /api/model

/** Сегмент модели в периоде (метка model в metric_samples). */
export interface ModelSegment {
  name: string;
  from: number;
  to: number;
}

export type FinishReasons = Record<string, number>;

/** KPI вкладки «Модель» (GET /api/model?from&to, docs/api-contracts.md). */
export interface ModelKpi {
  running: number | null;
  waiting: number | null;
  prompt_rate: number | null;
  gen_rate: number | null;
  ttft_p50: number | null;
  ttft_p95: number | null;
  tpot_p50: number | null;
  tpot_p95: number | null;
  e2e_p95: number | null;
  kv_cache: number | null;
  prefix_hit_rate: number | null;
  preemptions: number | null;
  requests_finished: number | null;
  finish_reasons: FinishReasons | null;
}

export interface ModelData {
  models: ModelSegment[];
  kpi: ModelKpi | null;
  distributions: {
    prompt_tokens: [number, number][];
    generation_tokens: [number, number][];
  } | null;
}

export function modelUrl(from: number, to: number, model?: string | null): string {
  let u = `/api/model?from=${from}&to=${to}`;
  if (model) u += `&model=${encodeURIComponent(model)}`;
  return u;
}

/** Историческая модель (GET /api/model/models, F4.4). */
export interface ModelInfo {
  name: string;
  from: number;
  to: number;
  count: number;
}

export const MODELS_URL = "/api/model/models";

// -------------------------------------------------------------- /api/cost

export function costUrl(from: number, to: number): string {
  return `/api/cost?from=${from}&to=${to}`;
}

// -------------------------------------------------------------- /api/system

/** Строка топ-процессов бэка: [pid, имя, RSS MiB, CPU %]. */
export type TopProcRow = [number, string, number, number];

/** Снимок GET /api/system (поля — api/app/api/routes.py). */
export interface SystemSnapshot {
  ts: number;
  cpu: {
    usage: number | null;
    per_core: (number | null)[];
    steal_pct: number | null;
    freq_mhz: number | null;
    load: (number | null)[];
  };
  ram: {
    total_mb: number | null;
    used_mb: number | null;
    available_mb: number | null;
    swap_used_mb: number | null;
  };
  disks: { mount: string; used_pct: number }[];
  io: { read_mb_s: number | null; write_mb_s: number | null };
  net: { rx_mbps: number | null; tx_mbps: number | null };
  psi: Record<string, Record<string, number | null>>;
  top_cpu: TopProcRow[];
  top_ram: TopProcRow[];
}

// ------------------------------------------------------------------- polling

export interface PollState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** принудительный повтор запроса */
  refresh: () => void;
}

/**
 * «Сейчас» (epoch-с), тикающее с заданным интервалом: окно Live для
 * вспомогательных запросов (p50, finish reasons) пересчитывается по интервалу,
 * а не при каждом рендере (иначе URL и эффект зависели бы от времени рендера).
 */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/**
 * Опрос REST-эндпоинта. url === null — запрос не выполняется (нет периода).
 * intervalMs: 0 — один раз при смене URL; >0 — повторный опрос.
 */
export function usePoll<T>(url: string | null, intervalMs = 0): PollState<T> {
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  const [state, setState] = useState<{
    data: T | null;
    loading: boolean;
    error: string | null;
  }>({ data: null, loading: url != null, error: null });

  useEffect(() => {
    if (url == null) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = () => {
      fetchJson<T>(url)
        .then((data) => {
          if (!cancelled) setState({ data, loading: false, error: null });
        })
        .catch((e: unknown) => {
          if (!cancelled)
            setState((s) => ({
              data: s.data,
              loading: false,
              error: e instanceof Error ? e.message : "Ошибка API",
            }));
        });
    };
    load();
    if (intervalMs > 0) timer = setInterval(load, intervalMs);
    return () => {
      cancelled = true;
      if (timer != null) clearInterval(timer);
    };
  }, [url, intervalMs, tick]);

  return { ...state, refresh };
}

/** Окно Live для вспомогательных запросов (p50, finish reasons), с. */
export const LIVE_WINDOW_S = 5 * 60;
/** Период повторного опроса вспомогательных данных в Live, мс. */
export const LIVE_REFRESH_MS = 60_000;

// ------------------------------------------------------------------ /api/logs

/** Поля автопарсинга stat-строк vLLM (api/app/logs/patterns.py). */
export interface VllmLogStats {
  running?: number;
  waiting?: number;
  kv_cache_pct?: number;
  avg_prompt_throughput?: number;
  avg_generation_throughput?: number;
  prefix_cache_hit_rate_pct?: number;
}

/** Строка GET /api/logs (``ts`` — epoch-миллисекунды UTC, новые сверху). */
export interface LogRow {
  id: number;
  ts: number;
  level: string;
  source: string;
  line: string;
  stats: VllmLogStats | null;
}

export interface LogsPageData {
  rows: LogRow[];
  total: number;
  has_more: boolean;
  from: number;
  to: number;
}

/** День в GET /api/logs/stats: ``day`` — epoch-с локальной полуночи. */
export interface LogDayStat {
  day: number;
  levels: Record<string, number>;
  total: number;
}

export interface LogsStatsData {
  from: number;
  to: number;
  by_day: LogDayStat[];
}

/** Источник /api/logs/sources (статусы tailer'а). */
export interface LogSourceInfo {
  name: string;
  type: "file" | "docker";
  path: string | null;
  container: string | null;
  status: string;
  last_error: string | null;
}

export interface LogSourcesData {
  sources: LogSourceInfo[];
  poll_seconds: number;
}

/** Строка SSE /api/logs/live. */
export interface LiveLogLine {
  ts: number;
  source: string;
  level: string;
  line: string;
}

export interface LogsFilterParams {
  from: number;
  to: number;
  /** CSV-список уровней (ERROR,WARN,...); пустое — без фильтра */
  level?: string;
  query?: string;
  source?: string;
  offset?: number;
  limit?: number;
}

export function logsUrl(p: LogsFilterParams): string {
  const q = new URLSearchParams();
  q.set("from", String(p.from));
  q.set("to", String(p.to));
  if (p.level) q.set("level", p.level);
  if (p.query) q.set("query", p.query);
  if (p.source) q.set("source", p.source);
  q.set("offset", String(p.offset ?? 0));
  q.set("limit", String(p.limit ?? 100));
  return `/api/logs?${q.toString()}`;
}

export function logsStatsUrl(from: number, to: number): string {
  return `/api/logs/stats?from=${from}&to=${to}`;
}

/** Ссылка-загрузка экспорта (txt/csv) с текущими фильтрами. */
export function logsExportUrl(
  p: LogsFilterParams & { format?: "txt" | "csv"; limit?: number },
): string {
  const q = new URLSearchParams();
  q.set("from", String(p.from));
  q.set("to", String(p.to));
  if (p.level) q.set("level", p.level);
  if (p.query) q.set("query", p.query);
  if (p.source) q.set("source", p.source);
  q.set("format", p.format ?? "txt");
  q.set("limit", String(p.limit ?? 100_000));
  return `/api/logs/export?${q.toString()}`;
}

export const LOGS_SOURCES_URL = "/api/logs/sources";
export const LOGS_LIVE_URL = "/api/logs/live";

// ------------------------------------------------------------------ /api/alerts (F4.1)

export interface AlertRule {
  id: string;
  title: string;
  level: "warning" | "critical";
  metric: string | null;
  op: ">" | "<" | null;
  value: number | null;
  source: "vllm" | "gpu" | "system" | null;
  for_s: number;
  cooldown_s: number;
  enabled: boolean;
}

export interface AlertsSettings {
  enabled: boolean;
  telegram_webhook: string;
  webhook_configured: boolean;
  rules: AlertRule[];
}

export interface AlertEvent {
  id: number;
  rule: string;
  level: string;
  status: "active" | "resolved";
  message: string;
  triggered_at: number;
  resolved_at: number | null;
}

export interface AlertsData {
  /** активные: {rule, triggered_at} */
  active: { rule: string; triggered_at: number }[];
  recent: AlertEvent[];
}

export const ALERTS_URL = "/api/alerts";
export const ALERTS_SETTINGS_URL = "/api/settings/alerts";
export const ALERTS_TEST_URL = "/api/alerts/test";

/** PUT /api/settings/alerts — частичное обновление. */
export interface AlertsUpdate {
  enabled?: boolean;
  telegram_webhook?: string | null;
  rules?: AlertRule[];
  reset_rules?: boolean;
}

export async function putAlertsSettings(body: AlertsUpdate): Promise<{ updated_at: number }> {
  return putJson(ALERTS_SETTINGS_URL, body);
}

export async function testAlerts(): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(ALERTS_TEST_URL, { method: "POST", cache: "no-store" });
  const j = (await res.json()) as { ok?: boolean; detail?: string };
  if (!res.ok) throw new Error(j.detail ?? `HTTP ${res.status}`);
  return j as { ok: boolean; message: string };
}

// ---------------------------------------------------------- /api/health (F4.3)

export interface HealthSummary {
  service: {
    version: string;
    uptime_s: number;
    db_path: string;
    db_size_mb: number | null;
    counts: Record<string, number | null>;
  };
  sources: Record<string, {
    status: string;
    last_ok_ts: number | null;
    last_poll_ts: number | null;
    last_error: string | null;
  }> & { last_sample_ts: Record<string, number | null> };
  model: string | null;
  gpus: {
    id: number | null;
    name: string | null;
    power_w: number | null;
    temp_c: number | null;
    util_pct: number | null;
    mem_used_pct: number | null;
    throttle: string[];
    ecc_uncorrectable: number | null;
  }[];
  system: { disks: { mount: string; used_pct: number }[] };
  logs: { errors_24h: number; critical_24h: number; warnings_24h: number };
  alerts_active: number;
}

export const HEALTH_SUMMARY_URL = "/api/health/summary";
