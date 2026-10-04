"""REST-роут /live (SSE): пакет кэша снимков каждые 2 с (ТЗ §7).

Формат пакета — docs/api-contracts.md; источник offline → его блок null.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ._shared import src_ok, system_snapshot_from_metrics, throttle_names

router = APIRouter(prefix="/api")

# Период пакета и heartbeat (ТЗ §7 / docs/api-contracts.md)
LIVE_INTERVAL_S = 2.0
LIVE_HEARTBEAT_S = 15.0


def _gpu_block(snap: dict | None) -> tuple[dict | None, list[dict[str, Any]] | None]:
    """(gpu_total, gpus) из кэша снимка GPU; snap None → (None, None)."""
    if not snap:
        return None, None
    gpus: list[dict[str, Any]] = [
        dict(d) for _, d in sorted(snap.get("gpus", {}).items(), key=lambda t: t[0])
    ]
    for g in gpus:
        g["throttle"] = throttle_names(g.get("throttle"))
    power = [g["power_w"] for g in gpus if g.get("power_w") is not None]
    mem_used = [g["mem_used_mib"] for g in gpus if g.get("mem_used_mib") is not None]
    mem_total = [g["mem_total_mib"] for g in gpus if g.get("mem_total_mib") is not None]
    total = {
        "power_w": round(sum(power), 1) if power else None,
        "mem_used_mib": round(sum(mem_used), 1) if mem_used else None,
        "mem_total_mib": round(sum(mem_total), 1) if mem_total else None,
    }
    return total, gpus


def _build_live_packet(request: Request) -> dict[str, Any]:
    """Пакет SSE (JSON-формат — docs/api-contracts.md): только кэш снимков
    коллекторов (app.state), без SQL и без новых опросов."""
    snaps = request.app.state.snapshots
    statuses = request.app.state.statuses
    v_ok, g_ok, s_ok = (
        src_ok(statuses, "vllm"),
        src_ok(statuses, "gpu"),
        src_ok(statuses, "system"),
    )
    v = snaps.get("vllm") if v_ok else None
    s = snaps.get("system") if s_ok else None

    kpi = None
    model = None
    if v:
        m = v.get("metrics", {})
        q = m.get("prefix_cache_queries_rate")
        h = m.get("prefix_cache_hits_rate")
        rolling = m.get("prefix_hit_rate_60s")  # сглаживание ~60 с (коллектор)
        p60 = m.get("prompt_tokens_rate_60s")
        g60 = m.get("generation_tokens_rate_60s")
        kpi = {
            "running": m.get("num_requests_running"),
            "waiting": m.get("num_requests_waiting"),
            # rolling ~60 с, иначе 5-с снапшот (issue #1: 5-с окно мигает 0↔10k)
            "prompt_rate": p60 if p60 is not None else m.get("prompt_tokens_rate"),
            "gen_rate": g60 if g60 is not None else m.get("generation_tokens_rate"),
            "kv_cache": m.get("kv_cache_usage"),
            "prefix_hit_rate": (
                rolling
                if rolling is not None
                else ((h / q) if (q and h is not None) else None)
            ),
            "ttft_p95": m.get("ttft_p95"),
            "ttft_p50": m.get("ttft_p50"),
            "tpot_p95": m.get("tpot_p95"),
            "tpot_p50": m.get("tpot_p50"),
            "e2e_p95": m.get("e2e_latency_p95"),
            "preemptions_rate": m.get("num_preemptions_rate"),
        }
        model = v.get("model")

    gpu_total, gpus = _gpu_block(snaps.get("gpu") if g_ok else None)

    # system — полный снимок (cpu/ram/disks/io/net/psi) из кэша коллектора;
    # один формат с /api/system (system_snapshot_from_metrics)
    system: dict[str, Any] | None = None
    if s:
        system = system_snapshot_from_metrics(s.get("metrics", {}), s.get("ts") or int(time.time()))

    return {
        "ts": int(time.time()),
        "sources": {
            "vllm": "ok" if v_ok else "offline",
            "gpu": "ok" if g_ok else "offline",
            "system": "ok" if s_ok else "offline",
        },
        "model": model,
        "kpi": kpi,
        "gpu_total": gpu_total,
        "gpus": gpus,
        "system": system,
        "alerts_active": (
            request.app.state.alerts_engine.active_count()
            if getattr(request.app.state, "alerts_engine", None)
            else 0
        ),
    }


@router.get("/live")
async def live(request: Request) -> StreamingResponse:
    """SSE: пакет кэша снимков (vLLM+GPU+система) каждые 2 с (ТЗ §7).

    Формат пакета — docs/api-contracts.md; источник offline → его блок null.
    Heartbeat-комментарий ``: ping`` раз в ~15 с. Отключение клиента —
    CancelledError в генераторе (завершается чисто, без ошибок)."""

    async def gen():
        last_ping = time.monotonic()
        yield "retry: 2000\n\n"
        while True:
            packet = _build_live_packet(request)
            yield f"data: {json.dumps(packet, separators=(',', ':'), allow_nan=False)}\n\n"
            deadline = time.monotonic() + LIVE_INTERVAL_S
            while True:
                remain = deadline - time.monotonic()
                if remain <= 0:
                    break
                if time.monotonic() - last_ping >= LIVE_HEARTBEAT_S:
                    yield ": ping\n\n"
                    last_ping = time.monotonic()
                await asyncio.sleep(min(0.25, remain))

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
