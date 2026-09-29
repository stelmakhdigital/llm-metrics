"""REST-роуты F0 (ТЗ §7): health / metrics / overview / gpus / system / live.

Времена — epoch-секунды UTC (клиент отображает в локальном времени сервера).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..collectors.gpu import THROTTLE_REASON_NAMES, GpuCollector
from ..model_api import build_model_response
from ..query import downsample
from ..storage.db import rows_to_dicts

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

RAW_MAX_SPAN_S = 24 * 3600
# hourly — для периодов до ~2 недель; суточные точки — для месяца (ТЗ §4/§8.3)
HOURLY_MAX_SPAN_S = 14 * 86400

SNAPSHOT_METRICS = (
    "gpu_power",
    "gpu_util",
    "gpu_mem_used_mib",
    "gpu_mem_total_mib",
    "gpu_temp",
    "gpu_clock_sm",
    "gpu_clock_mem",
    "gpu_throttle_reasons",
    "gpu_ecc_correctable",
    "gpu_ecc_uncorrectable",
    "num_requests_running",
    "num_requests_waiting",
    "kv_cache_usage",
    "cpu_usage",
    "cpu_steal_pct",
    "cpu_freq_mhz",
    "load_avg_1",
    "load_avg_5",
    "load_avg_15",
    "ram_total_mb",
    "ram_used_mb",
    "ram_available_mb",
    "swap_used_mb",
    "disk_read_mb_s",
    "disk_write_mb_s",
    "net_rx_mbps",
    "net_tx_mbps",
)


def _db(request: Request):
    return request.app.state.db


async def last_values(
    request: Request, metrics: tuple[str, ...]
) -> dict[tuple[str, int | None], tuple[int, float]]:
    """Последние (ts, value) по метрикам; gpu-метрики — по каждой gpu."""
    db = _db(request)
    ph = ",".join("?" * len(metrics))
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT s.metric, s.gpu, s.ts, s.value
                FROM metric_samples s
                JOIN (SELECT metric, COALESCE(gpu, -1) AS g, MAX(ts) AS mt
                      FROM metric_samples WHERE metric IN ({ph})
                      GROUP BY metric, COALESCE(gpu, -1)) m
                ON s.metric = m.metric AND COALESCE(s.gpu, -1) = m.g AND s.ts = m.mt""",
            list(metrics),
        )
    )
    out: dict[tuple[str, int | None], tuple[int, float]] = {}
    for r in rows:
        gpu = None if r["gpu"] == -1 else r["gpu"]
        out[(r["metric"], gpu)] = (r["ts"], r["value"])
    return out


async def _latest_model(request: Request) -> str | None:
    rows = rows_to_dicts(
        await _db(request).execute_fetchall(
            """SELECT model FROM metric_samples
               WHERE source = 'vllm' AND model IS NOT NULL
               ORDER BY ts DESC LIMIT 1"""
        )
    )
    return rows[0]["model"] if rows else None


async def _gpu_snapshot(request: Request, live: bool = False) -> list[dict[str, Any]]:
    """Снимок всех GPU: последняя выборка каждой метрики (или живое NVML)."""
    devs = rows_to_dicts(
        await _db(request).execute_fetchall(
            "SELECT id, name, total_mem_mib, pci_bus FROM gpu_devices ORDER BY id"
        )
    )
    if live:
        collector: GpuCollector | None = getattr(request.app.state, "gpu_collector", None)
        if collector is not None:
            try:
                samples, dev_rows = await collector.poll()
                by_gpu: dict[int, dict[str, Any]] = {r["id"]: {} for r in dev_rows}
                for s in samples:
                    if s.gpu is not None and s.gpu in by_gpu:
                        by_gpu[s.gpu][s.metric] = s.value
                names = {r["id"]: r for r in dev_rows}
                return [
                    {
                        "id": gid,
                        "name": names.get(gid, {}).get("name"),
                        "pci_bus": names.get(gid, {}).get("pci_bus"),
                        "total_mem_mib": names.get(gid, {}).get("total_mem_mib"),
                        "power_w": by_gpu[gid].get("gpu_power"),
                        "util_pct": by_gpu[gid].get("gpu_util"),
                        "mem_used_mib": by_gpu[gid].get("gpu_mem_used_mib"),
                        "mem_total_mib": by_gpu[gid].get("gpu_mem_total_mib"),
                        "temp_c": by_gpu[gid].get("gpu_temp"),
                        "clock_sm_mhz": by_gpu[gid].get("gpu_clock_sm"),
                        "clock_mem_mhz": by_gpu[gid].get("gpu_clock_mem"),
                        "throttle_reasons": by_gpu[gid].get("gpu_throttle_reasons"),
                        "ecc_correctable": by_gpu[gid].get("gpu_ecc_correctable"),
                        "ecc_uncorrectable": by_gpu[gid].get("gpu_ecc_uncorrectable"),
                        "ts": int(time.time()),
                    }
                    for gid in sorted(by_gpu)
                ]
            except Exception as e:  # live-снимок не удался — даём из БД
                log.warning("live GPU snapshot failed: %s", e)
    last = await last_values(request, SNAPSHOT_METRICS)
    gpus: list[dict[str, Any]] = []
    for d in devs:
        gid = d["id"]
        gpus.append(
            {
                "id": gid,
                "name": d["name"],
                "pci_bus": d["pci_bus"],
                "total_mem_mib": d["total_mem_mib"],
                "power_w": _v(last, ("gpu_power", gid)),
                "util_pct": _v(last, ("gpu_util", gid)),
                "mem_used_mib": _v(last, ("gpu_mem_used_mib", gid)),
                "mem_total_mib": _v(last, ("gpu_mem_total_mib", gid))
                or d["total_mem_mib"],
                "temp_c": _v(last, ("gpu_temp", gid)),
                "clock_sm_mhz": _v(last, ("gpu_clock_sm", gid)),
                "clock_mem_mhz": _v(last, ("gpu_clock_mem", gid)),
                "throttle_reasons": _v(last, ("gpu_throttle_reasons", gid)),
                "ecc_correctable": _v(last, ("gpu_ecc_correctable", gid)),
                "ecc_uncorrectable": _v(last, ("gpu_ecc_uncorrectable", gid)),
                "ts": _ts(last, "gpu_power", gid),
            }
        )
    # gpu_devices может быть пуст, если опрос ещё не был успешен,
    # но выборки уже есть — не потеряем gpu, которых нет в справочнике
    seen = {g["id"] for g in gpus}
    for (metric, gid), (ts, val) in last.items():
        if metric != "gpu_power" or gid is None or gid in seen:
            continue
        gpus.append(
            {
                "id": gid,
                "name": None,
                "pci_bus": None,
                "total_mem_mib": _v(last, ("gpu_mem_total_mib", gid)),
                "power_w": val,
                "util_pct": None,
                "mem_used_mib": None,
                "mem_total_mib": None,
                "temp_c": None,
                "clock_sm_mhz": None,
                "clock_mem_mhz": None,
                "throttle_reasons": None,
                "ecc_correctable": None,
                "ecc_uncorrectable": None,
                "ts": ts,
            }
        )
    gpus.sort(key=lambda g: g["id"])
    return gpus


def _v(last, key: tuple[str, int | None]) -> Any:
    e = last.get(key)
    return e[1] if e else None


def _ts(last, metric: str, gid: int | None) -> Any:
    e = last.get((metric, gid))
    return e[0] if e else None


async def _aggregate_series(
    db,
    table: str,
    col: str,
    metric: str,
    gpu: int | None,
    start: int,
    to: int,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Строки (col, avg) из metric_hourly/metric_daily.

    ``gpu`` задан — только эта gpu; иначе — AVG по строкам gpu за окно
    (для не-GPU-метрик одна строка с gpu=NULL — как раньше).
    ``model`` задан — только строки этой модели."""
    mcond = " AND model = ?" if model is not None else ""
    if gpu is not None:
        sql = (
            f"SELECT {col}, avg FROM {table} "
            f"WHERE metric = ? AND gpu = ?{mcond} AND {col} >= ? AND {col} < ? ORDER BY {col}"
        )
        params: tuple = (metric, gpu, *( (model,) if model is not None else () ), start, to)
    else:
        sql = (
            f"SELECT {col}, AVG(avg) AS avg FROM {table} "
            f"WHERE metric = ?{mcond} AND {col} >= ? AND {col} < ? "
            f"GROUP BY {col} ORDER BY {col}"
        )
        params = (metric, *( (model,) if model is not None else () ), start, to)
    return rows_to_dicts(await db.execute_fetchall(sql, params))


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

    # последний замер по каждому основному источнику
    last_rows = rows_to_dicts(
        await db.execute_fetchall(
            "SELECT source, MAX(ts) AS ts FROM metric_samples GROUP BY source"
        )
    )
    last_sample = {r["source"]: r["ts"] for r in last_rows}

    model = await _latest_model(request)

    gpus = []
    snap = request.app.state.snapshots.get("gpu") if _src_ok(request.app.state.statuses, "gpu") else None
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
                    "throttle": _throttle_names(g.get("throttle")),
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

    Результат даунсемплируется до ≤1500 точек (min-max decimation).
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
            "num_requests_running": _v(last, ("num_requests_running", None)),
            "num_requests_waiting": _v(last, ("num_requests_waiting", None)),
            "kv_cache_usage": _v(last, ("kv_cache_usage", None)),
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
        g["throttle_reason_names"] = _throttle_names(g.get("throttle_reasons"))
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

    top_cpu, top_ram = _top_processes()
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
        "top_cpu": top_cpu,
        "top_ram": top_ram,
        "ts": int(time.time()),
    }


def _top_processes(n: int = 5) -> tuple[list[list[Any]], list[list[Any]]]:
    """Топ-N процессов по CPU и по RAM (psutil, вне БД)."""
    try:
        import psutil
    except ImportError:
        return [], []
    procs: list[tuple[int, str, int, float]] = []
    for p in psutil.process_iter():
        try:
            procs.append(
                (
                    p.pid,
                    p.name()[:80],
                    (p.memory_info().rss // (1024 * 1024)),
                    p.cpu_percent(),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    fmt = lambda lst: [[pid, name, rss, cpu] for pid, name, rss, cpu in lst]  # noqa: E731
    top_ram = fmt(sorted(procs, key=lambda x: x[2], reverse=True)[:n])
    top_cpu = fmt(sorted(procs, key=lambda x: x[3], reverse=True)[:n])
    return top_cpu, top_ram


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
    """F4.4: исторический список моделей (сегментация метки ``model``)."""
    rows = rows_to_dicts(
        await _db(request).execute_fetchall(
            """SELECT model AS name, MIN(ts) AS from_ts, MAX(ts) AS to_ts, COUNT(*) AS n
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


# ------------------------------------------------------------------------ live
# Период пакета и heartbeat (ТЗ §7 / docs/api-contracts.md)
LIVE_INTERVAL_S = 2.0
LIVE_HEARTBEAT_S = 15.0


def _src_ok(statuses, name: str) -> bool:
    return statuses[name].status == "online"


def _throttle_names(mask: Any) -> list[str]:
    """NVML-маска троттлинга → имена причин.

    Ключи `THROTTLE_REASON_NAMES` — **значения** битов (1, 2, 4, …, 128);
    ищем по `mask & bit`, а не по позиции (issue #2)."""
    if not isinstance(mask, (int, float)) or not mask:
        return []
    m = int(mask)
    return [
        THROTTLE_REASON_NAMES.get(b, f"bit_{b}")
        for b in (1, 2, 4, 8, 16, 32, 64, 128)
        if m & b
    ]


def _gpu_block(snap: dict | None) -> tuple[dict | None, list[dict[str, Any]] | None]:
    """(gpu_total, gpus) из кэша снимка GPU; snap None → (None, None)."""
    if not snap:
        return None, None
    gpus: list[dict[str, Any]] = [
        dict(d) for _, d in sorted(snap.get("gpus", {}).items(), key=lambda t: t[0])
    ]
    for g in gpus:
        g["throttle"] = _throttle_names(g.get("throttle"))
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
        _src_ok(statuses, "vllm"),
        _src_ok(statuses, "gpu"),
        _src_ok(statuses, "system"),
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
            "tpot_p95": m.get("tpot_p95"),
            "e2e_p95": m.get("e2e_latency_p95"),
            "preemptions_rate": m.get("num_preemptions_rate"),
        }
        model = v.get("model")

    gpu_total, gpus = _gpu_block(snaps.get("gpu") if g_ok else None)

    system = None
    if s:
        sm = s.get("metrics", {})
        system = {
            "cpu": sm.get("cpu_usage"),
            "load1": sm.get("load_avg_1"),
            "ram_used_mib": sm.get("ram_used_mb"),
            "ram_total_mib": sm.get("ram_total_mb"),
        }

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
