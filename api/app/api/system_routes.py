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
    """Снимок системы (последние выборки poller'а) + топ-5 процессов."""
    disks: list[dict[str, Any]] = []
    psi: dict[str, dict[str, float | None]] = {"cpu": {}, "memory": {}, "io": {}}
    db = _db(request)
    rows = rows_to_dicts(
        await db.execute_fetchall(
            """SELECT metric, ts, value FROM metric_samples
               WHERE source = 'system' AND ts = (
                 SELECT MAX(ts) FROM metric_samples
                 WHERE source = 'system' AND metric = metric_samples.metric
               )
               ORDER BY metric"""
        )
    )
    core_pairs: list[tuple[int, float | None]] = []
    for r in rows:
        m, v = r["metric"], r["value"]
        if m.startswith("disk_used_pct|"):
            disks.append({"mount": m.split("|", 1)[1], "used_pct": v})
        elif m.startswith("cpu_usage_core_"):
            try:
                core_pairs.append((int(m.rsplit("_", 1)[1]), v))
            except (ValueError, IndexError):
                pass
        elif m.startswith("psi_") and "_" in m[4:]:
            kind, tail = m[4:].split("_", 1)
            if kind in psi and tail.startswith("avg"):
                psi[kind][tail] = v
    core_values = [v for _, v in sorted(core_pairs, key=lambda t: t[0])]
    latest = {r["metric"]: r for r in rows}

    def lm(m: str) -> Any:
        r = latest.get(m)
        return r["value"] if r else None

    return {
        "cpu": {
            "usage": lm("cpu_usage"),
            "per_core": core_values,
            "steal_pct": lm("cpu_steal_pct"),
            "freq_mhz": lm("cpu_freq_mhz"),
            "load": [lm("load_avg_1"), lm("load_avg_5"), lm("load_avg_15")],
        },
        "ram": {
            "total_mb": lm("ram_total_mb"),
            "used_mb": lm("ram_used_mb"),
            "available_mb": lm("ram_available_mb"),
            "swap_used_mb": lm("swap_used_mb"),
        },
        "disks": sorted(disks, key=lambda d: d["mount"]),
        "io": {"read_mb_s": lm("disk_read_mb_s"), "write_mb_s": lm("disk_write_mb_s")},
        "net": {"rx_mbps": lm("net_rx_mbps"), "tx_mbps": lm("net_tx_mbps")},
        "psi": psi,
        "ts": int(time.time()),
    }
