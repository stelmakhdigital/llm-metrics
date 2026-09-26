# Контракт API F1 (SSE + /api/model) — сверяют бек-агент и UI-агенты

## GET /api/live (SSE)
- `Content-Type: text/event-stream`, события: один тип, строка `data: <json>`.
- Пакет каждые 2 с (heartbeat при пустых данных — всё равно отправлять).
```json
{
  "ts": 1756200000,
  "sources": {"vllm": "ok", "gpu": "ok", "system": "ok"},
  "model": "qwen3.8-27b-dflash2",
  "kpi": {"running": 3, "waiting": 0, "prompt_rate": 12.4, "gen_rate": 34.1,
          "kv_cache": 42.0, "prefix_hit_rate": 0.12,
          "ttft_p95": 0.42, "tpot_p95": 0.021, "e2e_p95": 1.8, "preemptions_rate": 0.0},
  "gpu_total": {"power_w": 306.0, "mem_used_mib": 58675, "mem_total_mib": 128814},
  "gpus": [{"id": 0, "name": "RTX 5070 Ti", "power_w": 72.0, "power_limit_w": 300.0,
            "mem_used_mib": 14620, "mem_total_mib": 16303, "util": 43, "temp": 43,
            "sm_clock_mhz": 1500, "mem_clock_mhz": 1313, "throttle": [],
            "ecc_correctable": 0, "ecc_uncorrectable": 0}],
  "system": {"cpu": 12.5, "load1": 1.2, "ram_used_mib": 8192, "ram_total_mib": 65536}
}
```
- Источники offline: соответствующий блок = `null`, `sources.X = "offline"`.
- Данные — последние значения коллекторов (кэш последнего снимка), не новый опрос.

## GET /api/model?from&to
`from/to` — epoch-сек. Ответ:
```json
{
  "models": [{"name": "qwen3.8-27b-dflash2", "from": 1756200000, "to": 1756210000}],
  "kpi": {
    "running": 3, "waiting": 0,
    "prompt_rate": 12.4, "gen_rate": 34.1,          // средние tok/s за период
    "ttft_p50": 0.2, "ttft_p95": 0.42, "tpot_p50": 0.02, "tpot_p95": 0.021,
    "e2e_p95": 1.8,                                  // из сырых точек p95 за период (или hourly p95)
    "kv_cache": 42.0, "prefix_hit_rate": 0.12,
    "preemptions": 1, "requests_finished": 100,
    "finish_reasons": {"stop": 98, "length": 2}
  },
  "distributions": {
    "prompt_tokens": [[16, 400], [32, 300]],        // [le, count-дельта за период] из request_prompt_tokens_bucket
    "generation_tokens": [[16, 200]]
  }
}
```
- `models` — сегментация по метке `model` в metric_samples (для графика — вертикальные линии).
- Счётчики за период — дифф (первые/последние значения), finish reasons — по `request_success_total_{reason}`.
- Квантили: p50/p95 — по точкам сырых квантилей за период (точки уже посчитаны при скрейпе интерполяцией по buckets); e2e — p95 из тех же точек. Период >24ч — из hourly (p95-колонка).
- Графики вкладки «Модель» идут через существующий `/api/metrics/{metric}` (метрики: num_requests_running, num_requests_waiting, prompt_tokens_rate, generation_tokens_rate, ttft_p50, ttft_p95, itl_p50, itl_p95, tpot_p50, tpot_p95, e2e_p95, kv_cache_usage, prefix_hit_rate, preemptions_rate).
- Для distributions: коллектор vLLM дополнительно хранит кумулятивные счётчики `request_prompt_tokens_bucket_{le}` / `request_generation_tokens_bucket_{le}` (le — из лейблов, без `+Inf`).

## Кэша последнего снимка
Коллекторы держат в памяти последний снимок (dataclass/dict) — читают SSE/API без SQL.

## web: общий хук SSE (пишет UI-агент GPU, используют все вкладки — НОРМАТИВНАЯ сигнатура)
`web/src/lib/live.ts`:
```ts
export type GpuSnapshot = { id: number; name: string; power_w: number | null; power_limit_w: number | null;
  mem_used_mib: number | null; mem_total_mib: number | null; util: number | null; temp: number | null;
  sm_clock_mhz: number | null; mem_clock_mhz: number | null; throttle: string[];
  ecc_correctable: number; ecc_uncorrectable: number };
export type LivePacket = { ts: number; sources: Record<string, "ok" | "offline">;
  model: string | null; kpi: Record<string, number | null> | null;
  gpu_total: { power_w: number; mem_used_mib: number; mem_total_mib: number } | null;
  gpus: GpuSnapshot[] | null; system: Record<string, number> | null };
export function useLive(): {
  packet: LivePacket | null;        // последний пакет
  connected: boolean;                // SSE жив
  lastUpdate: number | null;         // ts последнего пакета (epoch c)
  powerHistory: { ts: number; power_w: number }[];  // ring ~5 мин из gpu_total
};
```
