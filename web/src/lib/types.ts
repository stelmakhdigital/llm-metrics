/**
 * Типы под контракты API из ТЗ §7. Время — epoch-секунды (БД хранит UTC).
 * Null/отсутствие точки = пропуск данных (разрыв в графике, не 0).
 */

/** Глобальный период выборки (переключатель в шапке). */
export type Period = "live" | "5m" | "1h" | "24h" | "7d" | "30d" | "custom";

/** Точка метрики для графика (downsampled выборка /api/metrics/{metric}). */
export interface MetricPoint {
  /** epoch-секунды */
  ts: number;
  /** значение; null — пропуск */
  value: number | null;
}

export type SourceState = "ok" | "degraded" | "offline";

export interface SourceStatus {
  state: SourceState;
  /** последняя успешная точка, epoch-с */
  last_seen?: number | null;
}

/** GET /api/overview — KPI шапки: статус источников, модель, мощности/VRAM. */
export interface SnapshotOverview {
  /** сводный статус: готов / деградация / оффлайн */
  status: SourceState;
  /** текущая модель (model_name из vLLM), null если неизвестна */
  model: string | null;
  sources: {
    vllm: SourceStatus;
    gpu: SourceStatus;
    system: SourceStatus;
  };
  /** суммарная мощность всех GPU, Вт (null = нет данных) */
  gpus_total_watts: number | null;
  /** занято / всего VRAM, GiB */
  vram_used_gib: number | null;
  vram_total_gib: number | null;
  /** момент снимка, epoch-с */
  updated_at: number;
}

// ----------------------------------------------------------- /api/cost (F2)

/** Суточная точка стоимости (день — epoch 00:00 UTC). */
export interface CostDayPoint {
  day: number;
  total: number;
  tokens: number;
  electricity: number;
  kwh: number;
  avg_power_w: number | null;
}

/** GET /api/cost?from&to (ТЗ §5.5/§6). Валюта — код из тарифов (USD). */
export interface CostData {
  currency: string;
  total: number;
  tokens_cost: number;
  elec_cost: number;
  kwh: number;
  avg_power_w: number | null;
  per_1k_out_tok: number | null;
  per_request: number | null;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  by_day: CostDayPoint[];
  /** [[epoch-с, накопленная стоимость], ...] */
  cumulative: [number, number][];
  power_by_day: { day: number; avg_power_w: number | null }[];
}

// ----------------------------------------------- /api/settings/cost (F2)

/** Версия тарифа (settings key='cost_rates'). */
export interface CostRateVersion {
  updated_at: number;
  currency: string;
  rate_per_kwh_usd: number;
  system_baseline_watts: number;
  token_prompt_per_million_usd: number;
  token_completion_per_million_usd: number;
}

/** GET /api/settings/cost: history — новые версии первыми. */
export interface CostRatesSettings {
  current: CostRateVersion | null;
  history: CostRateVersion[];
}

/** PUT /api/settings/cost — любая комбинация полей. */
export type CostRateUpdate = Partial<Omit<CostRateVersion, "updated_at">>;
