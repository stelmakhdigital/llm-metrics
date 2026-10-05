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

import json
import math
from typing import Any

from .storage.db import rows_to_dicts

RAW_SPAN_S = 24 * 3600
# Глубина сырых выборок (ретенция metric_samples). Окно глубже — сырых данных
# уже нет, считать дельты счётчиков от «старейшего доступного» образца нельзя
# (тихо заниженный счёт): KPI остаётся null (разрыв, не 0).
RAW_RETENTION_S = 168 * 3600

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
    db, from_: int, to: int, model: str | None = None
) -> dict[str, tuple[float, float]]:
    """{metric: (первое значение, последнее значение)} в [from, to] — только
    метрики счётчиков (finish reasons, buckets, preemptions, prefix).

    Точечные запросы по индексу (metric, ts): имена — одной короткой
    выборкой за последний час, значения — first/last LIMIT 1 по метрике
    (~200 запросов по ~0.1 мс). Любой скан 700k+ строк счётчиков за 24 ч
    — 1–4 с (issue perf).
    """
    mfilter = " AND model = ?" if model else ""
    mparam = [model] if model else []
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT DISTINCT metric FROM metric_samples
               WHERE ts >= ? AND ts <= ?{mfilter}
                 AND (metric LIKE 'request_success_total_%'
                      OR metric LIKE 'request_prompt_tokens_bucket_%'
                      OR metric LIKE 'request_generation_tokens_bucket_%'
                      OR metric IN ('num_preemptions_total',
                                    'prefix_cache_hits_total',
                                    'prefix_cache_queries_total'))""",
            [to - 3600, to, *mparam],
        )
    )
    if not rows:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        m = r["metric"]
        f = rows_to_dicts(
            await db.execute_fetchall(
                f"SELECT value FROM metric_samples WHERE metric = ? "
                f"AND ts >= ? AND ts <= ?{mfilter} ORDER BY ts LIMIT 1",
                [m, from_, to, *mparam],
            )
        )
        l = rows_to_dicts(
            await db.execute_fetchall(
                f"SELECT value FROM metric_samples WHERE metric = ? "
                f"AND ts >= ? AND ts <= ?{mfilter} ORDER BY ts DESC LIMIT 1",
                [m, from_, to, *mparam],
            )
        )
        if f and l and f[0]["value"] is not None and l[0]["value"] is not None:
            out[m] = (f[0]["value"], l[0]["value"])
    return out


async def _model_segments(
    db, from_: int, to: int, model: str | None = None
) -> list[dict[str, Any]]:
    """Сегменты моделей (name, from, to) за период.

    Источник — ``model_tokens`` (маленькая таблица, без полного скана
    metric_samples); агрегата нет — fallback на сырые выборки.
    """
    mfilter = " AND model = ?" if model else ""
    mparams = [(from_ // 3600) * 3600, to, *([model] if model else [])]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts
               FROM model_tokens
               WHERE ts >= ? AND ts < ?{mfilter}
               GROUP BY model ORDER BY from_ts""",
            mparams,
        )
    )
    if rows:
        return [
            {"name": r["name"], "from": r["from_ts"], "to": r["to_ts"]} for r in rows
        ]
    # fallback: сырые выборки (полный скан) — только когда агрегата нет
    rfilter = " AND model = ?" if model else ""
    rparams = [from_, to, *([model] if model else [])]
    rrows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts
               FROM metric_samples
               WHERE source = 'vllm' AND model IS NOT NULL
                 AND ts >= ? AND ts <= ?{rfilter}
               GROUP BY model ORDER BY from_ts""",
            rparams,
        )
    )
    return [
        {"name": r["name"], "from": r["from_ts"], "to": r["to_ts"]} for r in rrows
    ]


async def _raw_points(
    db, metrics: tuple[str, ...], from_: int, to: int, model: str | None = None
) -> dict[str, list[float]]:
    """Все сырые значения метрик в периоде, по метрикам (одна выборка)."""
    ph = ",".join("?" * len(metrics))
    mfilter = " AND model = ?" if model else ""
    params = [*metrics, from_, to, *([model] if model else [])]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"SELECT metric, value FROM metric_samples "
            f"WHERE metric IN ({ph}) AND ts >= ? AND ts <= ?" + mfilter,
            params,
        )
    )
    out: dict[str, list[float]] = {m: [] for m in metrics}
    for r in rows:
        if r["value"] is not None:
            out[r["metric"]].append(r["value"])
    return out


async def _hourly_stats(
    db, metric: str, from_: int, to: int, column: str, model: str | None = None
) -> float | None:
    """Взвешенное (по count) среднее колонки hourly-агрегата за период."""
    mcond = " AND model = ?" if model is not None else ""
    params: tuple = (metric, (from_ // 3600) * 3600, to, *( (model,) if model is not None else () ))
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"SELECT SUM({column} * count) AS sm, SUM(count) AS c "
            f"FROM metric_hourly WHERE metric = ? AND hour >= ? AND hour < ?{mcond}",
            params,
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

    ``model`` (F4.4): фильтр по метке модели. Период ≤24ч — сырые данные;
    >24ч — rates/квантили из ``metric_hourly`` (с 0004 агрегаты несут
    model). Счётчики (finish reasons, distributions, prefix, preemptions) на
    периоде >24ч — из агрегата ``model_tokens`` (дельты по часам; ``model=None``
    — сумма по всем моделям), чтобы не делать полный скан metric_samples;
    агрегата нет (или период ≤24ч) — дельты сырых счётчиков. Сегментация
    моделей — тоже из ``model_tokens`` (fallback на сырые). «Последние
    значения» (running/waiting/kv) — только сырые: при фильтре и периоде,
    выходящем за raw-ретенцию (168ч), — null.
    """
    resp = _empty_response()
    if from_ < 0 or to <= from_:
        return resp

    # --- сегментация по метке model (вертикальные линии на графике);
    # источник — агрегат model_tokens (маленькая таблица), fallback — сырые
    resp["models"] = await _model_segments(db, from_, to, model)

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
    if span <= RAW_SPAN_S:
        # --- средние rates + квантили: одна сырая выборка на все 7 метрик
        pts = await _raw_points(
            db,
            (
                "prompt_tokens_rate",
                "generation_tokens_rate",
                "ttft_p50",
                "ttft_p95",
                "tpot_p50",
                "tpot_p95",
                "e2e_latency_p95",
            ),
            from_,
            to,
            model,
        )
        pr, gr = pts["prompt_tokens_rate"], pts["generation_tokens_rate"]
        kpi["prompt_rate"] = sum(pr) / len(pr) if pr else None
        kpi["gen_rate"] = sum(gr) / len(gr) if gr else None
        kpi["ttft_p50"] = quantile_sorted(pts["ttft_p50"], 0.50)
        kpi["ttft_p95"] = quantile_sorted(pts["ttft_p95"], 0.95)
        kpi["tpot_p50"] = quantile_sorted(pts["tpot_p50"], 0.50)
        kpi["tpot_p95"] = quantile_sorted(pts["tpot_p95"], 0.95)
        kpi["e2e_p95"] = quantile_sorted(pts["e2e_latency_p95"], 0.95)
    else:
        # --- период >24ч: hourly (avg-колонка для p50/rates, p95-колонка для p95)
        kpi["prompt_rate"] = await _hourly_stats(db, "prompt_tokens_rate", from_, to, "avg", model)
        kpi["gen_rate"] = await _hourly_stats(db, "generation_tokens_rate", from_, to, "avg", model)
        kpi["ttft_p50"] = await _hourly_stats(db, "ttft_p50", from_, to, "avg", model)
        kpi["tpot_p50"] = await _hourly_stats(db, "tpot_p50", from_, to, "avg", model)
        kpi["ttft_p95"] = await _hourly_stats(db, "ttft_p95", from_, to, "p95", model)
        kpi["tpot_p95"] = await _hourly_stats(db, "tpot_p95", from_, to, "p95", model)
        kpi["e2e_p95"] = await _hourly_stats(db, "e2e_latency_p95", from_, to, "p95", model)

    # --- счётчики за период (дифф)
    # model-фильтр и период глубже raw-ретенции — из агрегата model_tokens
    # (issue #5); иначе — дельты сырых счётчиков
    # Счётчики за период: >24ч — из агрегата model_tokens (маленькая таблица,
    # без полного скана metric_samples; model=None — сумма по всем моделям);
    # агрегата нет или ≤24ч — дельты сырых счётчиков
    counters: dict[str, Any] = {}
    if span > RAW_SPAN_S:
        counters = await _model_tokens_summary(db, from_, to, model)
        # fallback на сырые дельты — только если окно покрывается raw-ретенцией;
        # глубже (сырых данных нет) — counters={} → KPI null (разрыв, не 0)
        if not counters and (to - from_) <= RAW_RETENTION_S:
            counters = await _first_last(db, from_, to, model)
    else:
        counters = await _first_last(db, from_, to, model)
    # finish reasons
    reasons: dict[str, int] = {}
    finished = 0
    has_reasons = False
    if "_summary" in counters:
        reasons = dict(counters.get("_finish_reasons") or {})
        finished = int(sum(reasons.values()))
        has_reasons = bool(reasons)
    else:
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
    prem = counters.get("_preemptions") if "_summary" in counters else _counter_delta(counters, "num_preemptions_total")
    if prem is not None:
        kpi["preemptions"] = int(prem)

    # prefix hit rate — Δhits/Δqueries
    if "_summary" in counters:
        hits = counters.get("_prefix_hits")
        queries = counters.get("_prefix_queries")
        if hits and queries and queries > 0:
            kpi["prefix_hit_rate"] = hits / queries
    else:
        hits = _counter_delta(counters, "prefix_cache_hits_total")
        queries = _counter_delta(counters, "prefix_cache_queries_total")
        if hits is not None and queries and queries > 0:
            kpi["prefix_hit_rate"] = hits / queries

    # --- distributions: Δ bucket-счётчиков
    if "_summary" in counters:
        for key in ("prompt_tokens", "generation_tokens"):
            dist = counters.get(f"_{key}_dist")
            if dist:
                resp["distributions"][key] = sorted(dist)
    else:
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


async def _model_tokens_summary(
    db, from_: int, to: int, model: str | None = None
) -> dict[str, Any]:
    """Сводка model_tokens за период (issue #5): дельты счётчиков, finish
    reasons, preemptions, prefix, distribution'ы. ``model=None`` — сумма по
    всем моделям в периоде. Пустой dict — данных нет."""
    mfilter = " AND model = ?" if model else ""
    mparams = [*([model] if model else []), (from_ // 3600) * 3600, to]
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT finish_reasons, preemptions, prefix_hits, prefix_queries,
                      prompt_dist, generation_dist
               FROM model_tokens WHERE 1=1{mfilter} AND ts >= ? AND ts < ?""",
            mparams,
        )
    )
    if not rows:
        return {}
    out: dict[str, Any] = {"_summary": True}
    out["_prefix_hits"] = sum(int(r["prefix_hits"]) for r in rows if r["prefix_hits"] is not None) or None
    out["_prefix_queries"] = (
        sum(int(r["prefix_queries"]) for r in rows if r["prefix_queries"] is not None)
        or None
    )
    out["_preemptions"] = (
        sum(int(r["preemptions"]) for r in rows if r["preemptions"] is not None) or None
    )
    finish: dict[str, int] = {}
    for r in rows:
        if not r["finish_reasons"]:
            continue
        try:
            for k, v in json.loads(r["finish_reasons"]).items():
                finish[k] = finish.get(k, 0) + int(v)
        except (TypeError, json.JSONDecodeError):
            continue
    out["_finish_reasons"] = finish
    for col, key in (("prompt_dist", "prompt_tokens"), ("generation_dist", "generation_tokens")):
        dist: list[list[Any]] = []
        for r in rows:
            if not r[col]:
                continue
            try:
                for le, d in json.loads(r[col]).items():
                    dist.append([_num(float(le)), int(d)])
            except (TypeError, json.JSONDecodeError, ValueError):
                continue
        # суммируем по le (несколько часов могут иметь один и тот же le)
        by_le: dict[float, int] = {}
        for le, d in dist:
            by_le[float(le)] = by_le.get(float(le), 0) + d
        out[f"_{key}_dist"] = [[_num(le), d] for le, d in sorted(by_le.items()) if d > 0]
    return out
