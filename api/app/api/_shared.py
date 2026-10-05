"""Общие хелперы REST-роутов: доступ к БД, последние выборки, снимок GPU.

Перенесено из routes.py (разбивка роутов по доменам; логика без изменений).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

from ..collectors.gpu import GpuCollector, THROTTLE_REASON_NAMES
from ..storage.db import rows_to_dicts

log = logging.getLogger(__name__)

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
    request: Request, metrics: tuple[str, ...], window_s: int = 7200
) -> dict[tuple[str, int | None], tuple[int, float]]:
    """Последние (ts, value) по метрикам; gpu-метрики — по каждой gpu.

    Окно ``window_s`` — только свежие выборки: под-запрос MAX(ts) идёт по
    индексу (metric, ts) только в пределах окна (без окна — скан всей
    истории метрики, ~2 с на 28 метрик). Источник, молчащий дольше окна,
    отдаёт null — в статусе он и так offline (STALE = 180 с).
    """
    db = _db(request)
    ph = ",".join("?" * len(metrics))
    since = int(time.time()) - window_s
    rows = rows_to_dicts(
        await db.execute_fetchall(
            f"""SELECT s.metric, s.gpu, s.ts, s.value
                FROM metric_samples s
                JOIN (SELECT metric, COALESCE(gpu, -1) AS g, MAX(ts) AS mt
                      FROM metric_samples
                      WHERE metric IN ({ph}) AND ts >= ?
                      GROUP BY metric, COALESCE(gpu, -1)) m
                ON s.metric = m.metric AND COALESCE(s.gpu, -1) = m.g AND s.ts = m.mt""",
            [*metrics, since],
        )
    )
    out: dict[tuple[str, int | None], tuple[int, float]] = {}
    for r in rows:
        gpu = None if r["gpu"] == -1 else r["gpu"]
        out[(r["metric"], gpu)] = (r["ts"], r["value"])
    return out


def v_(last, key: tuple[str, int | None]) -> Any:
    e = last.get(key)
    return e[1] if e else None


def ts_(last, metric: str, gid: int | None) -> Any:
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


async def _latest_model(request: Request) -> str | None:
    # Окно 1 ч — под (source, ts) индекс: модель не меняется чаще, чем
    # за час, а без окна — полный скан metric_samples по ts (~1.4 с).
    rows = rows_to_dicts(
        await _db(request).execute_fetchall(
            """SELECT model FROM metric_samples
               WHERE source = 'vllm' AND model IS NOT NULL AND ts >= ?
               ORDER BY ts DESC LIMIT 1""",
            (int(time.time()) - 3600,),
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
                "power_w": v_(last, ("gpu_power", gid)),
                "util_pct": v_(last, ("gpu_util", gid)),
                "mem_used_mib": v_(last, ("gpu_mem_used_mib", gid)),
                "mem_total_mib": v_(last, ("gpu_mem_total_mib", gid))
                or d["total_mem_mib"],
                "temp_c": v_(last, ("gpu_temp", gid)),
                "clock_sm_mhz": v_(last, ("gpu_clock_sm", gid)),
                "clock_mem_mhz": v_(last, ("gpu_clock_mem", gid)),
                "throttle_reasons": v_(last, ("gpu_throttle_reasons", gid)),
                "ecc_correctable": v_(last, ("gpu_ecc_correctable", gid)),
                "ecc_uncorrectable": v_(last, ("gpu_ecc_uncorrectable", gid)),
                "ts": ts_(last, "gpu_power", gid),
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
                "total_mem_mib": v_(last, ("gpu_mem_total_mib", gid)),
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


def system_snapshot_from_metrics(latest: dict[str, Any], ts: int) -> dict[str, Any]:
    """Метрики системы (имя → значение) → структура снимка (cpu/ram/disks/io/net/psi).

    Общая для ``/api/system`` (собирает latest из БД) и SSE-пакета live
    (берёт latest из кэша снимка) — единый формат для обеих выдач."""
    disks: list[dict[str, Any]] = []
    psi: dict[str, dict[str, float | None]] = {"cpu": {}, "memory": {}, "io": {}}
    core_pairs: list[tuple[int, float | None]] = []
    for m, v in latest.items():
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
    lm = latest.get
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
        "ts": ts,
    }


def src_ok(statuses, name: str) -> bool:
    return statuses[name].status == "online"


def throttle_names(mask: Any) -> list[str]:
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
