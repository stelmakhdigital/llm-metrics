"""REST-роуты модели (ТЗ §5.2 / F4.4): /model, /model/models."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query, Request

from ..model_api import build_model_response
from ..storage.db import rows_to_dicts
from ._shared import _db

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------- model
@router.get("/model")
async def model_period(
    request: Request,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """KPI за период по метрикам vLLM (docs/api-contracts.md, ТЗ §5.2).

    ``model`` (F4.4) — фильтр по модели: период считается только по данным
    этой модели (сырые данные, глубина = ретенция 168ч).
    """
    now = int(time.time())
    to = to if to is not None else now
    from_ = from_ if from_ is not None else to - 3600
    return await build_model_response(_db(request), from_, to, model=model)


@router.get("/model/models")
async def model_list(request: Request) -> dict[str, Any]:
    """F4.4: исторический список моделей (сегментация метки ``model``).

    Источник — агрегат ``model_tokens`` (маленькая таблица); без агрегата
    (до первого цикла) — fallback на сырые выборки.
    """
    db = _db(request)
    rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts,
                      COALESCE(SUM(prompt_tokens), 0)
                      + COALESCE(SUM(completion_tokens), 0) AS n
               FROM model_tokens GROUP BY model ORDER BY to_ts DESC"""
        )
    )
    if not rows:  # агрегатор ещё не набрал модель — сырые данные
        rows = rows_to_dicts(
            await db.execute_fetchall(
                """SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts,
                          COUNT(*) AS n
                   FROM metric_samples
                   WHERE source = 'vllm' AND model IS NOT NULL
                   GROUP BY model ORDER BY to_ts DESC"""
            )
        )
    return {
        "models": [
            {"name": r["name"], "from": r["from_ts"], "to": r["to_ts"], "count": r["n"]}
            for r in rows
        ]
    }
