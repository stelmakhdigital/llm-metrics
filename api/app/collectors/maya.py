"""Конвертер снимка ``GET /metrics`` Project Maya (JSON) → словарь метрик
в форме, которую отдаёт :func:`app.collectors.prom_parser.parse_prometheus`.

Project Maya — не vLLM: перед движком (``build/strata``) стоит свой
Python-сервер (``serve/server.py``), чей ``/metrics`` отдаёт JSON
(:mod:`app.collectors.vllm` ожидает Prometheus text format). Чтобы не
дублировать маппинг/агрегацию, конвертер собирает **те же логические
метрики-кандидаты** (имена с префиксом ``vllm:``), а дальше работает
неизменный :class:`app.collectors.vllm.VllmCollector`.

Маппинг (см. docs/CONFIG.md, раздел «Maya»):

* ``vllm:num_requests_running`` ← ``live.active``;
* ``vllm:num_requests_waiting`` ← ``live.queued``;
* ``vllm:kv_cache_usage_perc`` ← ``tiers.now.vram_used/vram_slots``
  (занятость экспертного кэша 0..1 — ближайший аналог kv_cache vLLM);
* ``vllm:prompt_tokens_total`` ← ``totals.prompt_tokens``;
* ``vllm:generation_tokens_total`` ← ``totals.output_tokens``;
* ``vllm:prefix_cache_hits_total`` ← ``totals.reused``;
* ``vllm:prefix_cache_queries_total`` ← ``totals.prompt_tokens``
  (**прокси**: в maya нет счётчика lookups префикс-кэша; hit-rate = 
  reused/prompt_tokens — заниженная, но устойчивая оценка);
* histogram'ы (p50/p95) — по окну завершённых запросов ``requests``
  (newest last, ~``requests_kept`` штук): ttft ← ``prompt_ms``,
  tpot ← ``decode_ms/output_tokens``, e2e ← ``duration_s``; counts —
  кумулятивные по окну (пересчитываются каждый опрос);
* ``vllm:request_{prompt,generation}_tokens_bucket`` — те же окна;
* ``vllm:num_preemptions_total``, ``vllm:request_success_total`` и
  ``queue_time`` в maya отсутствуют → соответствующие серии UI просто
  не получают точек (пропуски данных — разрывы, см. инварианты).

Лейбл ``model_name`` (для истории «Модель») — из ``engine.model``.
"""

from __future__ import annotations

import json

from .prom_parser import Metric, Series

__all__ = ["maya_to_metrics"]

# Суффикс логических histogram-ов: (базовое имя-кандидат vllm:*, поле
# запроса, edges в секундах, делитель мс→с). None в edges = +Inf.
_HISTOGRAMS: tuple[tuple[str, str, tuple[float | None, ...]], ...] = (
    # ttft: время до первого токена ≈ prompt_ms (prefill)
    ("vllm:time_to_first_token_seconds", "prompt_ms",
     (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, None)),
    # tpot: decode_ms / output_tokens
    ("vllm:request_time_per_output_token_seconds", "tpot",
     (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, None)),
    # e2e: полное время запроса
    ("vllm:e2e_request_latency_seconds", "duration_s",
     (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, None)),
)

# Bucket'ы длин prompt/generation: (имя-кандидат, поле, edges). +Inf не
# хранится (collector пропускает нечисловые le).
_TOKEN_BUCKETS: tuple[tuple[str, str, tuple[float, ...]], ...] = (
    ("vllm:request_prompt_tokens_bucket", "prompt_tokens",
     (1, 16, 64, 256, 1024, 4096, 16384, 65536)),
    ("vllm:request_generation_tokens_bucket", "output_tokens",
     (1, 16, 64, 256, 1024, 4096, 16384)),
)


def _buckets(values: list[float], edges: tuple) -> dict[str | None, int]:
    """Кумулятивные counts по окну: ``{le: count}``; None = +Inf."""
    counts: dict[str | None, int] = {}
    for le in edges:
        counts[None if le is None else str(le)] = sum(
            1 for v in values if le is None or v <= le
        )
    return counts


def _bucket_metric(name: str, counts: dict[str | None, int], labels: dict[str, str]) -> Metric:
    """Metric с сериями ``{name}_bucket{le=...}`` (лейбл le обязателен)."""
    met = Metric(type="histogram")
    for le, c in counts.items():
        if le is None:  # +Inf не числом — collector сам отсечёт по лейблу
            lab = dict(labels, le="+Inf")
        else:
            lab = dict(labels, le=le)
        met.series.append(Series(labels=lab, value=float(c)))
    return met


def maya_to_metrics(payload) -> dict[str, Metric]:
    """JSON-снимок maya → ``{имя метрики: Metric}`` (форма parse_prometheus).

    :param payload: распарсенный JSON (dict) — или сырой текст (строка),
        тогда парсится здесь. Битый JSON/не-объект → ``ValueError``.
    """
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("maya /metrics: ожидается JSON-объект")

    labels = {"engine": "maya"}
    model = (payload.get("engine") or {}).get("model")
    if model:
        labels["model_name"] = str(model)

    out: dict[str, Metric] = {}

    def put(name: str, value) -> None:
        if value is None:
            return
        met = out.setdefault(name, Metric(type="gauge"))
        met.series.append(Series(labels=dict(labels), value=float(value)))

    live = payload.get("live") or {}
    put("vllm:num_requests_running", live.get("active"))
    put("vllm:num_requests_waiting", live.get("queued"))

    tiers = payload.get("tiers") or {}
    now = tiers.get("now") or {}
    slots = now.get("vram_slots")
    used = now.get("vram_used")
    if slots and used is not None:
        put("vllm:kv_cache_usage_perc", used / slots)

    totals = payload.get("totals") or {}
    put("vllm:prompt_tokens_total", totals.get("prompt_tokens"))
    put("vllm:generation_tokens_total", totals.get("output_tokens"))
    put("vllm:prefix_cache_hits_total", totals.get("reused"))
    # Прокси (см. docstring): lookups в maya недоступны.
    put("vllm:prefix_cache_queries_total", totals.get("prompt_tokens"))

    # Histogram'ы и bucket'ы длин — по окну завершённых запросов.
    requests = payload.get("requests")
    if isinstance(requests, list) and requests:
        values: dict[str, list[float]] = {}
        for r in requests:
            if not isinstance(r, dict):
                continue
            prompt_ms = r.get("prompt_ms")
            out_tokens = r.get("output_tokens")
            if prompt_ms is not None:
                values.setdefault("prompt_ms", []).append(prompt_ms / 1000.0)
                if out_tokens:  # tpot = decode_ms / output_tokens
                    values.setdefault("tpot", []).append(
                        r.get("decode_ms") / out_tokens / 1000.0
                    )
            dur = r.get("duration_s")
            if dur is not None:
                values.setdefault("duration_s", []).append(float(dur))
            if r.get("prompt_tokens") is not None:
                values.setdefault("prompt_tokens", []).append(
                    float(r["prompt_tokens"])
                )
            if out_tokens is not None:
                values.setdefault("output_tokens", []).append(float(out_tokens))

        for name, field, edges in _HISTOGRAMS:
            vals = values.get(field)
            if not vals:
                continue
            out[name + "_bucket"] = _bucket_metric(
                name + "_bucket", _buckets(vals, edges), labels
            )
        for name, field, edges in _TOKEN_BUCKETS:
            vals = values.get(field)
            if not vals:
                continue
            out[name] = _bucket_metric(name, _buckets(vals, edges), labels)

    return out
