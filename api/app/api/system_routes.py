"""REST-роуты системы/GPU (ТЗ §7): overview / gpus / system.

Времена — epoch-секунды UTC (клиент отображает в локальном времени сервера).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query, Request

from ..storage.db import rows_to_dicts
from ._shared import (
    _db,
    _gpu_snapshot,
    _latest_model,
    last_values,
    system_snapshot_from_metrics,
    throttle_names,
    v_,
)

router = APIRouter(prefix="/api")


# -------------------------------------------------------------------- overview
@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    """KPI шапки (ТЗ §7): статусы источников, модель, мощности/VRAM."""
    gpus = await _gpu_snapshot(request)
    last = await last_values(
        request,
        ("num_requests_running", "num_requests_waiting", "kv_cache_usage"),
    )
    total_power = [g["power_w"] for g in gpus if g["power_w"] is not None]
    mem_used = [g["mem_used_mib"] for g in gpus if g["mem_used_mib"] is not None]
    mem_total = [g["total_mem_mib"] for g in gpus if g["total_mem_mib"] is not None]
    return {
        "sources": request.app.state.statuses.to_dict(),
        "model": await _latest_model(request),
        "vllm": {
            "num_requests_running": v_(last, ("num_requests_running", None)),
            "num_requests_waiting": v_(last, ("num_requests_waiting", None)),
            "kv_cache_usage": v_(last, ("kv_cache_usage", None)),
        },
        "gpus": gpus,
        "total_power_w": round(sum(total_power), 1) if total_power else None,
        "total_mem_used_mib": round(sum(mem_used), 1) if mem_used else None,
        "total_mem_mib": round(sum(mem_total), 1) if mem_total else None,
        "ts": int(time.time()),
    }


# ----------------------------------------------------------------------- gpus
@router.get("/gpus")
async def gpus(request: Request, live: bool = Query(False)) -> dict[str, Any]:
    """Снимок всех GPU (последние выборки poller'а; ``live=true`` — живое NVML)."""
    rows = await _gpu_snapshot(request, live=live)
    for g in rows:
        g["throttle_reason_names"] = throttle_names(g.get("throttle_reasons"))
    return {"gpus": rows, "live": live, "ts": int(time.time())}


# --------------------------------------------------------------------- system
@router.get("/system")
async def system(request: Request) -> dict[str, Any]:
    """Снимок системы (последние выборки poller'а) — единый формат с SSE-пакетом live."""
    db = _db(request)
    # Под (source, ts) индекс; окно 2 ч — источник, молчащий дольше,
    # и так offline (STALE = 180 с)
    rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT s.metric, s.value FROM metric_samples s
               JOIN (SELECT metric, MAX(ts) AS mt FROM metric_samples
                     WHERE source = 'system' AND ts >= ?
                     GROUP BY metric) m
               ON s.metric = m.metric AND s.ts = m.mt
               ORDER BY s.metric""",
            (int(time.time()) - 7200,),
        )
    )
    latest = {r["metric"]: r["value"] for r in rows}
    return system_snapshot_from_metrics(latest, int(time.time()))
