"""Δ счётчиков vLLM за часовое окно, раздельно по метке ``model`` (issue #5).

Используется агрегатором (написание ``model_tokens`` каждый цикл) и
``GET /api/model`` (сводка по модели для периодов глубже raw). Паттерн
``Aggregator._counter_delta``, но с фильтром model: дельта =
last(в окне) − last(до окна); None при отсутствии данных, разрыве >2 ч
или отрицательной дельте (рестарт процесса).
"""

from __future__ import annotations

import json
from typing import Any

FINISH_REASON_PREFIX = "request_success_total_"
DIST_PREFIXES: tuple[str, ...] = (
    "request_prompt_tokens_bucket_",
    "request_generation_tokens_bucket_",
)

_TOKEN_COUNTERS = ("prompt_tokens_total", "generation_tokens_total")


async def _last_before(db, metric: str, ts: int, model: str) -> tuple | None:
    rows = await db.execute_fetchall(
        """SELECT value, ts FROM metric_samples
           WHERE metric = ? AND ts < ? AND model = ? ORDER BY ts DESC LIMIT 1""",
        (metric, ts, model),
    )
    return (rows[0]["value"], rows[0]["ts"]) if rows else None


async def _last_in(db, metric: str, ts_from: int, ts_to: int, model: str) -> float | None:
    rows = await db.execute_fetchall(
        """SELECT value FROM metric_samples
           WHERE metric = ? AND ts >= ? AND ts < ? AND model = ? ORDER BY ts DESC LIMIT 1""",
        (metric, ts_from, ts_to, model),
    )
    return rows[0]["value"] if rows else None


async def delta_for_hour(db, metric: str, hour: int, model: str) -> int | None:
    """Δ ``metric`` за [hour, hour+3600) для ``model`` (None — см. модуль)."""
    last = await _last_in(db, metric, hour, hour + 3600, model)
    if last is None:
        return None
    prev = await _last_before(db, metric, hour, model)
    if prev is None or hour - prev[1] > 7200:
        return None
    d = int(round(last - prev[0]))
    return d if d >= 0 else None


async def hour_model_row(
    db, hour: int, model: str
) -> dict[str, Any] | None:
    """Строка ``model_tokens`` для (час, модель); None — данных нет."""
    prompt = await delta_for_hour(db, "prompt_tokens_total", hour, model)
    completion = await delta_for_hour(db, "generation_tokens_total", hour, model)
    preemptions = await delta_for_hour(db, "num_preemptions_total", hour, model)
    pfx_hits = await delta_for_hour(db, "prefix_cache_hits_total", hour, model)
    pfx_queries = await delta_for_hour(db, "prefix_cache_queries_total", hour, model)

    reasons: dict[str, int] = {}
    finished = 0
    rows = await db.execute_fetchall(
        """SELECT DISTINCT metric FROM metric_samples
           WHERE metric LIKE ? AND ts >= ? AND ts < ? AND model = ?""",
        (FINISH_REASON_PREFIX + "%", hour, hour + 3600, model),
    )
    for r in rows:
        d = await delta_for_hour(db, r["metric"], hour, model)
        if d is not None and d > 0:
            reasons[r["metric"][len(FINISH_REASON_PREFIX):]] = d
            finished += d

    dists: dict[str, dict[str, int]] = {p: {} for p in DIST_PREFIXES}
    rows = await db.execute_fetchall(
        """SELECT metric, value FROM metric_samples
           WHERE (metric LIKE ? OR metric LIKE ?) AND ts >= ? AND ts < ? AND model = ?
           ORDER BY metric""",
        (DIST_PREFIXES[0] + "%", DIST_PREFIXES[1] + "%", hour, hour + 3600, model),
    )
    for r in rows:
        for p in DIST_PREFIXES:
            if not r["metric"].startswith(p):
                continue
            le = r["metric"][len(p):]
            try:
                float(le)
            except ValueError:
                continue
            d = await delta_for_hour(db, r["metric"], hour, model)
            if d is not None and d >= 0:
                dists[p][le] = dists[p].get(le, 0) + d

    if prompt is None and completion is None and not reasons:
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "requests_finished": finished if reasons else None,
        "finish_reasons": json.dumps(reasons) if reasons else None,
        "preemptions": preemptions,
        "prefix_hits": pfx_hits,
        "prefix_queries": pfx_queries,
        "prompt_dist": json.dumps(dists[DIST_PREFIXES[0]])
        if dists[DIST_PREFIXES[0]]
        else None,
        "generation_dist": json.dumps(dists[DIST_PREFIXES[1]])
        if dists[DIST_PREFIXES[1]]
        else None,
    }
