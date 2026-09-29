"""Коллектор метрик vLLM (ТЗ §3.1, §5.2).

Опрос ``GET {url}{metrics_path}`` (Prometheus text format), ручной парсинг
(без prometheus_client) и маппинг **логическое имя → кандидаты имён метрик**,
чтобы переживать апгрейды vLLM (ТЗ §10 прим. 1).

Хранятся (source='vllm', с меткой ``model``):
* гейджи: ``num_requests_running``, ``num_requests_waiting``,
  ``kv_cache_usage`` (0..100, из ``kv_cache_usage_perc`` 0..1);
* rates счётчиков (Δ/Δt, защита от рестарта — отрицательный дельта
  пропускается): ``prompt_tokens_rate``, ``generation_tokens_rate``,
  ``prefix_cache_queries_rate``, ``prefix_cache_hits_rate``,
  ``num_preemptions_rate``;
* ``prefix_hit_rate`` — ratio hits_rate/queries_rate за интервал (0..1,
  та же шкала, что live-KPI/карточка и период в ``model_api``);
* ``prefix_hit_rate_60s`` — rolling за последние ~60 с (Δhits/Δqueries от
  самой старой точки окна; история ~90 с, на рестарт/нехватку истории —
  отсутствует);
* ``prompt_tokens_rate_60s`` / ``generation_tokens_rate_60s`` — rolling
  rates за последние ~60 с (та же история/окно; для сглаживания
  live-карточек «Токены prompt/s» и «Токены генерации/s») — issue #1;
* **сырые** счётчики (для токенизатора/периодов): ``*_total`` как есть;
* finish reasons: сырые счётчики ``request_success_total_{reason}``
  (stop/length/abort/error/... — любой лейбл ``finished_reason``);
* kвантили histogram-ов (p50/p95, интерполяция по buckets, ТЗ §5.2):
  ``ttft``, ``tpot``, ``itl``, ``e2e_latency``, ``queue_time`` →
  ``{имя}_p50`` / ``{имя}_p95``.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import httpx

from ..config import VllmSource
from .percentile import percentile_from_buckets
from .prom_parser import parse_prometheus

__all__ = ["Sample", "VllmCollector", "VllmError"]

# (logical_name, [кандидаты имён метрик], масштаб)
GAUGES: list[tuple[str, list[str], float]] = [
    ("num_requests_running", ["vllm:num_requests_running"], 1.0),
    ("num_requests_waiting", ["vllm:num_requests_waiting"], 1.0),
    ("kv_cache_usage", ["vllm:kv_cache_usage_perc"], 100.0),  # 0..1 → 0..100 %
]

# (logical_rate, logical_raw, [кандидаты имён счётчика])
COUNTERS: list[tuple[str, str, list[str]]] = [
    ("prompt_tokens_rate", "prompt_tokens_total", ["vllm:prompt_tokens_total"]),
    (
        "generation_tokens_rate",
        "generation_tokens_total",
        ["vllm:generation_tokens_total"],
    ),
    (
        "prefix_cache_queries_rate",
        "prefix_cache_queries_total",
        ["vllm:prefix_cache_queries_total"],
    ),
    (
        "prefix_cache_hits_rate",
        "prefix_cache_hits_total",
        ["vllm:prefix_cache_hits_total"],
    ),
    ("num_preemptions_rate", "num_preemptions_total", ["vllm:num_preemptions_total"]),
]

# (logical_base, [кандидаты базовых имён histogram])
HISTOGRAMS: list[tuple[str, list[str]]] = [
    ("ttft", ["vllm:time_to_first_token_seconds", "vllm:time_to_first_token"]),
    (
        "tpot",
        [
            "vllm:request_time_per_output_token_seconds",
            "vllm:time_per_output_token_seconds",
        ],
    ),
    ("itl", ["vllm:inter_token_latency_seconds"]),
    ("e2e_latency", ["vllm:e2e_request_latency_seconds"]),
    ("queue_time", ["vllm:request_queue_time_seconds"]),
]

# Сырые счётчики finish reasons (лейбл finished_reason → суффикс имени)
FINISH_REASON_METRIC = "vllm:request_success_total"

# Кумулятивные счётчики bucket'ов для гистограмм длин prompt/generation
# (docs/api-contracts.md: distributions /api/model): хранятся как
# ``request_prompt_tokens_bucket_{le}`` / ``request_generation_tokens_bucket_{le}``
# (le — числовое, ``+Inf`` не хранится)
TOKEN_BUCKET_METRICS: tuple[str, ...] = (
    "vllm:request_prompt_tokens_bucket",
    "vllm:request_generation_tokens_bucket",
)
TOKEN_BUCKET_PREFIX: dict[str, str] = {
    "vllm:request_prompt_tokens_bucket": "request_prompt_tokens_bucket_",
    "vllm:request_generation_tokens_bucket": "request_generation_tokens_bucket_",
}

# Показываемые (не сырые счётчики) метрики для кэша последнего снимка
SNAPSHOT_METRIC_NAMES: set[str] = (
    {logical for logical, _, _ in GAUGES}
    | {rate for rate, _, _ in COUNTERS}
    | {f"{base}_{sfx}" for base, _ in HISTOGRAMS for sfx in ("p50", "p95")}
    | {"prefix_hit_rate_60s", "prompt_tokens_rate_60s", "generation_tokens_rate_60s"}
)


class VllmError(RuntimeError):
    """Источник недоступен / не распознан."""


@dataclass
class Sample:
    metric: str
    ts: int
    value: float
    source: str
    gpu: int | None = None
    model: str | None = None


def _series_sum(metrics, name: str) -> float | None:
    """Сумма значений серии (несколько engine — сумма; одна — её значение).

    NaN/отсутствующие значения игнорируются; если все — None, вернуть None.
    """
    met = metrics.get(name)
    if met is None:
        return None
    vals = [s.value for s in met.series if s.value is not None and s.value == s.value]
    return sum(vals) if vals else None


def _first_label(metrics, name: str, label: str) -> str | None:
    met = metrics.get(name)
    if met is None:
        return None
    for s in met.series:
        v = s.labels.get(label)
        if v:
            return v
    return None


class VllmCollector:
    """Один poll = один GET /metrics.

    Состояние: предыдущие значения сырых счётчиков для расчёта rates
    (при отрицательном дельте — рестарт vLLM, rate пропускается).
    """

    def __init__(self, cfg: VllmSource):
        self.cfg = cfg
        self._prev: dict[str, tuple[int, float]] = {}  # raw name -> (ts, value)
        # История (ts, hits, queries, prompt_total, gen_total) для rolling
        # ~60 с (prefix hit rate + rates токенов, live-карточки; issue #1)
        self._roll_hist: list[tuple[int, float, float, float | None, float | None]] = []
        self.model_name: str | None = None  # кэш последнего известного имени
        # Кэш последнего снимка (F1, docs/api-contracts.md): без SQL читают
        # SSE /api/live и API. {"ts", "model", "metrics": {имя: значение}}
        self.last_snapshot: dict | None = None

    async def poll(self, client: httpx.AsyncClient, now: int | None = None) -> list[Sample]:
        now = int(now if now is not None else time.time())
        url = self.cfg.url.rstrip("/") + self.cfg.metrics_path
        try:
            resp = await client.get(url, timeout=self.cfg.request_timeout)
            resp.raise_for_status()
            text = resp.text
        except (httpx.HTTPError, OSError) as e:
            raise VllmError(f"GET {url} failed: {e}") from e

        metrics = parse_prometheus(text)
        model = self._resolve_model(metrics)
        samples: list[Sample] = []

        # Гейджи
        for logical, candidates, scale in GAUGES:
            val = None
            for name in candidates:
                val = _series_sum(metrics, name)
                if val is not None:
                    break
            if val is not None:
                samples.append(Sample(logical, now, val * scale, "vllm", None, model))

        # Счётчики: сырые значения + rates с защитой от рестарта
        rate_values: dict[str, float] = {}
        raw_values: dict[str, float] = {}
        for rate_name, raw_name, candidates in COUNTERS:
            raw = None
            for name in candidates:
                raw = _series_sum(metrics, name)
                if raw is not None:
                    break
            if raw is None:
                continue
            raw_values[raw_name] = raw
            samples.append(Sample(raw_name, now, raw, "vllm", None, model))
            prev = self._prev.get(raw_name)
            if prev is not None:
                prev_ts, prev_val = prev
                dt = now - prev_ts
                if dt > 0:
                    delta = raw - prev_val
                    if delta >= 0:  # иначе — рестарт процесса, пропускаем
                        r = delta / dt
                        samples.append(Sample(rate_name, now, r, "vllm", None, model))
                        rate_values[rate_name] = r
                    else:
                        samples.append(Sample(f"{raw_name}_restart", now, 1.0, "vllm", None, model))
            self._prev[raw_name] = (now, raw)

        # Prefix cache hit rate за интервал: hits_rate/queries_rate (0..1)
        q = rate_values.get("prefix_cache_queries_rate")
        h = rate_values.get("prefix_cache_hits_rate")
        if q and h is not None:
            samples.append(Sample("prefix_hit_rate", now, h / q, "vllm", None, model))

        # Rolling за последние ~60 с: prefix hit rate + rates токенов
        # (сглаживание live-карточек; issue #1)
        h_raw = raw_values.get("prefix_cache_hits_total")
        q_raw = raw_values.get("prefix_cache_queries_total")
        p_raw = raw_values.get("prompt_tokens_total")
        g_raw = raw_values.get("generation_tokens_total")
        if any(v is not None for v in (h_raw, q_raw, p_raw, g_raw)):
            hist = self._roll_hist
            last = hist[-1] if hist else None
            if last is not None:
                # рестарт vLLM — любой из счётчиков упал
                if (
                    (h_raw is not None and last[1] is not None and h_raw < last[1])
                    or (q_raw is not None and last[2] is not None and q_raw < last[2])
                    or (p_raw is not None and last[3] is not None and p_raw < last[3])
                    or (g_raw is not None and last[4] is not None and g_raw < last[4])
                ):
                    hist.clear()
            hist.append((now, h_raw, q_raw, p_raw, g_raw))
            while hist and now - hist[0][0] > 90:
                hist.pop(0)
            base = next(
                (pt for pt in reversed(hist[:-1]) if now - pt[0] >= 60), None
            )
            if base is not None:
                dt = now - base[0]
                dq = (q_raw or 0) - (base[2] or 0)
                dh = (h_raw or 0) - (base[1] or 0)
                if dq > 0 and dh >= 0:
                    samples.append(
                        Sample("prefix_hit_rate_60s", now, dh / dq, "vllm", None, model)
                    )
                if p_raw is not None and base[3] is not None and p_raw >= base[3] and dt > 0:
                    samples.append(
                        Sample("prompt_tokens_rate_60s", now, (p_raw - base[3]) / dt, "vllm", None, model)
                    )
                if g_raw is not None and base[4] is not None and g_raw >= base[4] and dt > 0:
                    samples.append(
                        Sample("generation_tokens_rate_60s", now, (g_raw - base[4]) / dt, "vllm", None, model)
                    )

        # Finish reasons — сырые счётчики с суффиксом {reason}
        met = metrics.get(FINISH_REASON_METRIC)
        if met is not None:
            for s in met.series:
                reason = s.labels.get("finished_reason")
                if not reason or s.value is None:
                    continue
                safe = reason.replace('"', "")
                samples.append(
                    Sample(f"request_success_total_{safe}", now, s.value, "vllm", None, model)
                )

        # Histogram'ы → p50/p95 интерполяцией по buckets
        for base, candidates in HISTOGRAMS:
            buckets = None
            for name in candidates:
                b = metrics.get(name + "_bucket")
                if b is not None and b.series:
                    buckets = []
                    for s in b.series:
                        le = s.labels.get("le")
                        if le is None or s.value is None:
                            continue
                        try:
                            le_f = float("inf") if le == "+Inf" else float(le)
                        except ValueError:
                            continue
                        buckets.append((le_f, s.value))
                    if buckets:
                        break
            if not buckets:
                continue
            for p, suffix in ((0.50, "p50"), (0.95, "p95")):
                q = percentile_from_buckets(buckets, p)
                if q is not None:
                    samples.append(Sample(f"{base}_{suffix}", now, q, "vllm", None, model))

        # Кумулятивные счётчики bucket'ов длин prompt/generation (без +Inf)
        for name in TOKEN_BUCKET_METRICS:
            met = metrics.get(name)
            if met is None:
                continue
            by_le: dict[float, float] = {}
            for s in met.series:
                le = s.labels.get("le")
                if le is None or s.value is None:
                    continue
                try:
                    le_f = float(le)
                except ValueError:
                    continue
                if not math.isfinite(le_f):
                    continue  # +Inf не храним
                by_le[le_f] = by_le.get(le_f, 0.0) + s.value  # несколько engine — сумма
            for le_f, val in by_le.items():
                le_s = str(int(le_f)) if le_f.is_integer() else str(le_f)
                samples.append(
                    Sample(
                        TOKEN_BUCKET_PREFIX[name] + le_s, now, val, "vllm", None, model
                    )
                )

        # Кэш последнего снимка (единая точка чтения — app.state, main.py)
        self.last_snapshot = {
            "ts": now,
            "model": model,
            "metrics": {
                s.metric: s.value for s in samples if s.metric in SNAPSHOT_METRIC_NAMES
            },
        }
        return samples

    def _resolve_model(self, metrics) -> str | None:
        """Имя модели: лейбл model_name → конфиг → кэш предыдущего."""
        for name, met in metrics.items():
            if not name.startswith("vllm:"):
                continue
            for s in met.series:
                v = s.labels.get("model_name")
                if v:
                    self.model_name = v
                    return v
        if self.cfg.model_name:
            return self.cfg.model_name
        return self.model_name
