"""REST-роуты: health / metrics (остальные домены — *_routes.py рядом).

Времена — epoch-секунды UTC (клиент отображает в локальном времени сервера).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request

from .. import __version__
from ..query import downsample
from ..storage.db import rows_to_dicts
from ._shared import (
    _aggregate_series,
    _db,
    _latest_model,
    src_ok,
    throttle_names,
)

router = APIRouter(prefix="/api")

RAW_MAX_SPAN_S = 24 * 3600
# hourly — для периодов до ~2 недель; суточные точки — для месяца (ТЗ §4/§8.3)
HOURLY_MAX_SPAN_S = 14 * 86400


# --------------------------------------------------------------------- health
@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "uptime_s": round(time.time() - request.app.state.started_at, 1),
        "db_path": request.app.state.config.storage.sqlite_path,
        "sources": request.app.state.statuses.to_dict(),
    }


# ------------------------------------------------------------------- health*
@router.get("/health/summary")
async def health_summary(request: Request) -> dict[str, Any]:
    """F4.3 «Health»-страница: сводный статус сервиса/источников/модели/
    GPU/системы/логов/алертов (без тяжёлых SQL — только последние выборки)."""
    db = _db(request)
    db_path = Path(request.app.state.config.storage.sqlite_path)
    try:
        db_size_mb = round(db_path.stat().st_size / 1e6, 2) if db_path.exists() else None
    except OSError:
        db_size_mb = None

    counts: dict[str, int | None] = {}
    for table in ("metric_samples", "log_entries"):
        try:
            r = await db.execute_fetchall(f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = r[0]["n"] if r else None
        except Exception:  # noqa: BLE001
            counts[table] = None

    # последний замер по каждому основному источнику (точечный seek по
    # индексу (source, ts); GROUP BY source — скан всей таблицы, ~6 с)
    last_rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT 'vllm' AS source, MAX(ts) AS ts FROM metric_samples WHERE source = 'vllm'
               UNION ALL SELECT 'gpu', MAX(ts) FROM metric_samples WHERE source = 'gpu'
               UNION ALL SELECT 'system', MAX(ts) FROM metric_samples WHERE source = 'system'"""
        )
    )
    last_sample = {r["source"]: r["ts"] for r in last_rows}

    model = await _latest_model(request)

    gpus = []
    snap = request.app.state.snapshots.get("gpu") if src_ok(request.app.state.statuses, "gpu") else None
    if snap:
        for g in snap.get("gpus", {}).values():
            gpus.append(
                {
                    "id": g.get("id"),
                    "name": g.get("name"),
                    "power_w": g.get("power_w"),
                    "temp_c": g.get("temp"),
                    "util_pct": g.get("util"),
                    "mem_used_pct": (
                        round(g["mem_used_mib"] / g["mem_total_mib"] * 100, 1)
                        if g.get("mem_used_mib") is not None and g.get("mem_total_mib")
                        else None
                    ),
                    "throttle": throttle_names(g.get("throttle")),
                    "ecc_uncorrectable": g.get("ecc_uncorrectable"),
                }
            )

    # диски: последние выборки disk_used_pct|*
    disk_rows = await db.execute_fetchall(
        """SELECT s.metric, s.value FROM metric_samples s
           JOIN (SELECT metric, MAX(ts) AS mt FROM metric_samples
                 WHERE metric LIKE 'disk_used_pct|%' AND ts >= ?
                 GROUP BY metric) m
           ON s.metric = m.metric AND s.ts = m.mt""",
        (int(time.time()) - 600,),
    )
    system_block: dict[str, Any] = {"disks": []}
    for r in disk_rows:
        system_block["disks"].append(
            {"mount": r["metric"].split("|", 1)[1], "used_pct": r["value"]}
        )

    # логи: ошибки/предупреждения за 24ч
    now = int(time.time())
    log_rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT level, COUNT(*) AS n FROM log_entries
               WHERE ts >= ? AND level IN ('ERROR','CRITICAL','WARNING')
               GROUP BY level""",
            ((now - 86400) * 1000,),
        )
    )
    logs = {"errors_24h": 0, "critical_24h": 0, "warnings_24h": 0}
    for r in log_rows:
        if r["level"] == "ERROR":
            logs["errors_24h"] = r["n"]
        elif r["level"] == "CRITICAL":
            logs["critical_24h"] = r["n"]
        else:
            logs["warnings_24h"] = r["n"]

    engine = getattr(request.app.state, "alerts_engine", None)
    return {
        "service": {
            "version": __version__,
            "uptime_s": round(time.time() - request.app.state.started_at, 1),
            "db_path": db_path,
            "db_size_mb": db_size_mb,
            "counts": counts,
        },
        "sources": {
            **request.app.state.statuses.to_dict(),
            "last_sample_ts": last_sample,
        },
        "model": model,
        "gpus": gpus,
        "system": system_block,
        "logs": logs,
        "alerts_active": engine.active_count() if engine else 0,
    }


# -------------------------------------------------------------------- metrics
@router.get("/metrics/{metric}")
async def metric_series(
    request: Request,
    metric: str,
    from_: int | None = Query(None, alias="from"),
    to: int | None = None,
    gpu: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Точки графика. Выбор источника (ТЗ §4/§8.3):

    * ≤24ч — сырые выборки ``metric_samples``;
    * ≤14д — ``metric_hourly`` (avg по часам, точка в середине часа);
    * больше (месяц и шире) — ``metric_daily`` (avg по суткам, точка в
      середине суток); при пустом daily — fallback на hourly.

    Результат даунсемплируется до ≤200 точек (среднее по временным бакетам,
    как у hourly-агрегата) — короткие периоды выглядят как длинные.
    """
    now = int(time.time())
    to = to if to is not None else now
    from_ = from_ if from_ is not None else to - 3600
    if from_ < 0 or to <= from_:
        return {"metric": metric, "source": None, "count": 0, "points": []}
    span = to - from_
    db = _db(request)
    if model is not None:
        # F4.4: фильтр по модели. ≤24ч — сырые; до 14д — hourly; дальше —
        # daily (fallback hourly). Глубина = ретенция агрегатов; более старые
        # окна без метки model (до миграции 0004) в фильтр не попадают.
        if span <= RAW_MAX_SPAN_S:
            rows = rows_to_dicts(
                await db.execute_fetchall(
                    "SELECT ts, value FROM metric_samples "
                    "WHERE metric = ? AND model = ? AND ts >= ? AND ts <= ? ORDER BY ts",
                    (metric, model, from_, to),
                )
            )
            points = [[r["ts"], r["value"]] for r in rows]
            if points:
                return {
                    "metric": metric,
                    "source": "raw",
                    "count": len(points),
                    "points": downsample(points),
                }
        if span <= HOURLY_MAX_SPAN_S:
            rows = await _aggregate_series(
                db, "metric_hourly", "hour", metric, None, (from_ // 3600) * 3600, to, model
            )
            points = [[r["hour"] + 1800, r["avg"]] for r in rows if r["avg"] is not None]
            return {
                "metric": metric,
                "source": "hourly" if points else None,
                "count": len(points),
                "points": downsample(points),
            }
        rows = await _aggregate_series(
            db, "metric_daily", "day", metric, None, (from_ // 86400) * 86400, to, model
        )
        points = [[r["day"] + 43200, r["avg"]] for r in rows if r["avg"] is not None]
        source = "daily"
        if not points:
            rows = await _aggregate_series(
                db, "metric_hourly", "hour", metric, None, (from_ // 3600) * 3600, to, model
            )
            points = [[r["hour"] + 1800, r["avg"]] for r in rows if r["avg"] is not None]
            source = "hourly"
        return {
            "metric": metric,
            "source": source if points else None,
            "count": len(points),
            "points": downsample(points),
        }
    if span <= RAW_MAX_SPAN_S:
        sql = (
            "SELECT ts, value FROM metric_samples "
            "WHERE metric = ? AND ts >= ? AND ts <= ?"
            + (" AND gpu = ?" if gpu is not None else "")
            + " ORDER BY ts"
        )
        params = (metric, from_, to, gpu) if gpu is not None else (metric, from_, to)
        rows = rows_to_dicts(await db.execute_fetchall(sql, params))
        points = [[r["ts"], r["value"]] for r in rows]
        source = "raw"
        if not points:
            # Сырые могли быть очищены ретенцией — падаем на hourly
            rows = await _aggregate_series(
                db, "metric_hourly", "hour", metric, gpu, (from_ // 3600) * 3600, to
            )
            points = [[r["hour"] + 1800, r["avg"]] for r in rows if r["avg"] is not None]
            source = "hourly"
    elif span <= HOURLY_MAX_SPAN_S:
        rows = await _aggregate_series(
            db, "metric_hourly", "hour", metric, gpu, (from_ // 3600) * 3600, to
        )
        points = [[r["hour"] + 1800, r["avg"]] for r in rows if r["avg"] is not None]
        source = "hourly"
    else:
        rows = await _aggregate_series(
            db, "metric_daily", "day", metric, gpu, (from_ // 86400) * 86400, to
        )
        points = [[r["day"] + 43200, r["avg"]] for r in rows if r["avg"] is not None]
        source = "daily"
        if not points:
            # daily ещё не накоплен — падаем на hourly
            rows = await _aggregate_series(
                db, "metric_hourly", "hour", metric, gpu, (from_ // 3600) * 3600, to
            )
            points = [[r["hour"] + 1800, r["avg"]] for r in rows if r["avg"] is not None]
            source = "hourly"
    points = downsample(points)
    return {"metric": metric, "source": source, "count": len(points), "points": points}
