"""Логика GET /api/model (docs/api-contracts.md, ТЗ §5.2).

KPI за период по метрикам vLLM:
* ``running``/``waiting``/``kv_cache`` — последние значения в периоде;
* ``prompt_rate``/``gen_rate`` — средние tok/s за период;
* квантили (``ttft_p50/p95``, ``tpot_p50/p95``, ``e2e_p95``):
  - период ≤24ч — по точкам сырых квантилей (``{base}_p50``/``{base}_p95``,
    посчитанных при скрейпе интерполяцией по buckets) — k-квантиль (линейная
    интерполяция) по точкам соответствующего квантиля (p50/p95 не смешиваются);
  - период >24ч — из ``metric_hourly``: p95-колонка (для p95), avg-колонка
    (для p50 и для средних rates);
* ``prefix_hit_rate`` — Δhits_total/Δqueries_total за период;
* ``preemptions`` — Δ num_preemptions_total;
* ``finish_reasons`` — Δ по ``request_success_total_{reason}``
  (``requests_finished`` — сумма);
* ``distributions`` — Δ кумулятивных счётчиков
  ``request_prompt_tokens_bucket_{le}`` / ``request_generation_tokens_bucket_{le}``;
* ``models`` — сегментация по метке ``model`` (смена модели в периоде).
"""

from __future__ import annotations

import math
from typing import Any

from .storage.db import rows_to_dicts

RAW_SPAN_S = 24 * 3600

_TOKEN_BUCKET_PREFIXES = (
    "request_prompt_tokens_bucket_",
    "request_generation_tokens_bucket_",
)


def quantile_sorted(values: list[float], p: float) -> float | None:
    """K-quantile по значениям (линейная интерполяция, метод ТЗ §5.2)."""
    if not values or not (0.0 <= p <= 1.0):
        return None
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    idx = p * (len(v) - 1)
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return v[lo]
    frac = idx - lo
    return v[lo] * (1 - frac) + v[hi] * frac


def _le_number(metric: str, prefix: str) -> float | None:
    try:
        return float(metric[len(prefix) :])
    except ValueError:
        return None


def _num(x: float | int) -> Any:
    """int для целых, иначе float (формат le в distributions)."""
    f = float(x)
    return int(f) if f.is_integer() else f


def _counter_delta(
    pairs: dict[str, tuple[float, float]], metric: str
) -> float | None:
    """Дельта счётчика (последнее − первое); None — данных нет,
    отрицательное (рестарт) — None."""
    p = pairs.get(metric)
    if p is None:
        return None
    d = p[1] - p[0]
    return d if d >= 0 else None


async def _first_last(
    db, metrics_prefix_like: str, from_: int, to: int, model: str | None = None
) -> dict[str, tuple[float, float]]:
    """{metric: (первое значение, последнее значение)} в [from, to]."""
    mfilter = " AND model = ?" if model else ""
    mparams = [model] if model else []
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT s.metric, s.value FROM metric_samples s
               JOIN (SELECT metric, MIN(ts) AS mt FROM metric_samples
                     WHERE metric LIKE ? AND ts >= ? AND ts <= ?{mfilter}
                     GROUP BY metric) m
               ON s.metric = m.metric AND s.ts = m.mt""",
            [metrics_prefix_like, from_, to, *mparams],
        )
    )
    for r in rows:
        first[r["metric"]] = r["value"]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT s.metric, s.value FROM metric_samples s
               JOIN (SELECT metric, MAX(ts) AS mt FROM metric_samples
                     WHERE metric LIKE ? AND ts >= ? AND ts <= ?{mfilter}
                     GROUP BY metric) m
               ON s.metric = m.metric AND s.ts = m.mt""",
            [metrics_prefix_like, from_, to, *mparams],
        )
    )
    for r in rows:
        last[r["metric"]] = r["value"]
    out: dict[str, tuple[float, float]] = {}
    for m in set(first) | set(last):
        if m in first and m in last:
            out[m] = (first[m], last[m])
    return out


async def _raw_points(
    db, metrics: tuple[str, ...], from_: int, to: int, model: str | None = None
) -> list[float]:
    """Все сырые значения метрик в периоде (одним списком)."""
    ph = ",".join("?" * len(metrics))
    mfilter = " AND model = ?" if model else ""
    params = [*metrics, from_, to, *([model] if model else [])]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"SELECT value FROM metric_samples "
            f"WHERE metric IN ({ph}) AND ts >= ? AND ts <= ?" + mfilter,
            params,
        )
    )
    return [r["value"] for r in rows if r["value"] is not None]


async def _hourly_stats(db, metric: str, from_: int, to: int, column: str) -> float | None:
    """Взвешенное (по count) среднее колонки hourly-агрегата за период."""
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"SELECT SUM({column} * count) AS sm, SUM(count) AS c "
            f"FROM metric_hourly WHERE metric = ? AND hour >= ? AND hour < ?",
            (metric, (from_ // 3600) * 3600, to),
        )
    )
    r = rows[0]
    if not r["c"]:
        return None
    return r["sm"] / r["c"]


def _empty_response() -> dict[str, Any]:
    return {
        "models": [],
        "kpi": {
            "running": None,
            "waiting": None,
            "prompt_rate": None,
            "gen_rate": None,
            "ttft_p50": None,
            "ttft_p95": None,
            "tpot_p50": None,
            "tpot_p95": None,
            "e2e_p95": None,
            "kv_cache": None,
            "prefix_hit_rate": None,
            "preemptions": None,
            "requests_finished": None,
            "finish_reasons": {},
        },
        "distributions": {"prompt_tokens": [], "generation_tokens": []},
    }


async def build_model_response(
    db, from_: int, to: int, model: str | None = None
) -> dict[str, Any]:
    """Сборка ответа GET /api/model за период [from, to].

    ``model`` (F4.4): фильтр по метке модели — только сырые данные
    (hourly/daily метки модели не имеют; глубина = ретенция raw 168ч),
    raw-расчёт применяется к любому периоду.
    """
    resp = _empty_response()
    if from_ < 0 or to <= from_:
        return resp

    # --- сегментация по метке model (вертикальные линии на графике)
    mfilter = " AND model = ?" if model else ""
    mparams = [from_, to, *([model] if model else [])]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts
               FROM metric_samples
               WHERE source = 'vllm' AND model IS NOT NULL
                 AND ts >= ? AND ts <= ?{mfilter}
               GROUP BY model ORDER BY from_ts""",
            mparams,
        )
    )
    resp["models"] = [
        {"name": r["name"], "from": r["from_ts"], "to": r["to_ts"]} for r in rows
    ]

    kpi = resp["kpi"]

    # --- последние значения (running / waiting / kv_cache)
    async def last_value(metric: str) -> float | None:
        mfilter = " AND model = ?" if model else ""
        params = [metric, from_, to, *([model] if model else [])]
        rs = rows_to_dicts(
            await db.execute_fetchall(
                "SELECT value FROM metric_samples WHERE metric = ? AND ts >= ? AND ts <= ? "
                + mfilter
                + " ORDER BY ts DESC LIMIT 1",
                params,
            )
        )
        return rs[0]["value"] if rs else None

    kpi["running"] = await last_value("num_requests_running")
    kpi["waiting"] = await last_value("num_requests_waiting")
    kpi["kv_cache"] = await last_value("kv_cache_usage")

    span = to - from_
    if span <= RAW_SPAN_S or model is not None:
        # --- средние rates по сырым точкам
        for key, metric in (
            ("prompt_rate", "prompt_tokens_rate"),
            ("gen_rate", "generation_tokens_rate"),
        ):
            pts = await _raw_points(db, (metric,), from_, to, model)
            kpi[key] = sum(pts) / len(pts) if pts else None

        # --- квантили по точкам сырых квантилей (отдельные серии)
        for key, base in (("ttft", "ttft"), ("tpot", "tpot")):
            p50_pts = await _raw_points(db, (f"{base}_p50",), from_, to, model)
            p95_pts = await _raw_points(db, (f"{base}_p95",), from_, to, model)
            kpi[f"{key}_p50"] = quantile_sorted(p50_pts, 0.50)
            kpi[f"{key}_p95"] = quantile_sorted(p95_pts, 0.95)
        e2e_pts = await _raw_points(db, ("e2e_latency_p95",), from_, to, model)
        kpi["e2e_p95"] = quantile_sorted(e2e_pts, 0.95)
    else:
        # --- период >24ч: hourly (avg-колонка для p50/rates, p95-колонка для p95)
        kpi["prompt_rate"] = await _hourly_stats(db, "prompt_tokens_rate", from_, to, "avg")
        kpi["gen_rate"] = await _hourly_stats(db, "generation_tokens_rate", from_, to, "avg")
        kpi["ttft_p50"] = await _hourly_stats(db, "ttft_p50", from_, to, "avg")
        kpi["tpot_p50"] = await _hourly_stats(db, "tpot_p50", from_, to, "avg")
        kpi["ttft_p95"] = await _hourly_stats(db, "ttft_p95", from_, to, "p95")
        kpi["tpot_p95"] = await _hourly_stats(db, "tpot_p95", from_, to, "p95")
        kpi["e2e_p95"] = await _hourly_stats(db, "e2e_latency_p95", from_, to, "p95")

    # --- счётчики за период (дифф)
    counters = await _first_last(db, "%", from_, to, model)
    # finish reasons
    reasons: dict[str, int] = {}
    finished = 0
    has_reasons = False
    for m, (first_v, last_v) in counters.items():
        if not m.startswith("request_success_total_"):
            continue
        d = last_v - first_v
        if d < 0:
            continue
        reason = m[len("request_success_total_") :]
        reasons[reason] = int(reasons.get(reason, 0) + d)
        finished += d
        has_reasons = True
    if has_reasons:
        kpi["finish_reasons"] = dict(sorted(reasons.items()))
        kpi["requests_finished"] = int(finished)

    # preemptions
    prem = _counter_delta(counters, "num_preemptions_total")
    if prem is not None:
        kpi["preemptions"] = int(prem)

    # prefix hit rate — Δhits/Δqueries
    hits = _counter_delta(counters, "prefix_cache_hits_total")
    queries = _counter_delta(counters, "prefix_cache_queries_total")
    if hits is not None and queries and queries > 0:
        kpi["prefix_hit_rate"] = hits / queries

    # --- distributions: Δ bucket-счётчиков
    for prefix, key in zip(_TOKEN_BUCKET_PREFIXES, ("prompt_tokens", "generation_tokens")):
        dist: list[list[Any]] = []
        for m, (first_v, last_v) in counters.items():
            if not m.startswith(prefix):
                continue
            le = _le_number(m, prefix)
            if le is None:
                continue
            d = last_v - first_v
            if d > 0:
                dist.append([_num(le), int(d)])
        resp["distributions"][key] = sorted(dist)
    return resp
