"""Коллектор метрик GPU через NVML (pynvml), ТЗ §3.1/§5.3.

* Период опроса — 10 с (конфиг).
* ``pynvml`` импортируется defensively: без драйвера/библиотеки poller
  помечает источник ``offline`` с причиной, приложение продолжает жить
  (ТЗ §8.2).
* При первом успешном опросе устройства автозаполняются в
  ``gpu_devices`` (name, total_mem_mib, pci_bus).

Метрики (source='gpu', gpu=<индекс>):
``gpu_power`` (W), ``gpu_util`` (%), ``gpu_mem_used_mib``,
``gpu_mem_total_mib``, ``gpu_temp`` (°C), ``gpu_clock_sm`` (MHz),
``gpu_clock_mem`` (MHz), ``gpu_throttle_reasons`` (bitmask NVML, 0 = нет),
``gpu_ecc_correctable`` / ``gpu_ecc_uncorrectable`` (сырые кумулятивные
счётчики — период считается API дельтой).
"""

from __future__ import annotations

import time
from typing import Any

from ..config import GpuSource
from .vllm import Sample

__all__ = ["GpuCollector", "GpuError"]

THROTTLE_REASON_NAMES = {
    1: "gpu_slowdown",
    2: "sync_boost",
    4: "sw_power_brake",
    8: "hw_slowdown",
    16: "hw Thermal slowdown",
    32: "hw power brake",
    64: "sw thermal cap",
    128: "sw power cap",
}


class GpuError(RuntimeError):
    """NVML недоступен или опрос устройства не удался."""


class GpuCollector:
    def __init__(self, cfg: GpuSource):
        self.cfg = cfg
        self._initialized = False
        self._nvml = None  # модуль pynvml
        self._init_error: str | None = None
        self.devices: list[int] = []  # индексы устройств
        self.ready = False
        # Кэш последнего снимка (F1, docs/api-contracts.md):
        # {"ts", "gpus": {idx: {id, name, power_w, power_limit_w, util, ...}}}
        self.last_snapshot: dict | None = None

    # ------------------------------------------------------------------ init
    def _ensure_init(self) -> None:
        """Инициализация NVML (в рабочем потоке!). Идемпотентна."""
        if self._initialized:
            return
        self._initialized = True
        try:
            import pynvml  # type: ignore
        except ImportError as e:
            self._init_error = f"pynvml не установлен: {e}"
            return
        try:
            pynvml.nvmlInit()
        except Exception as e:  # NVMLError: нет драйвера и т.п.
            self._init_error = f"nvmlInit failed: {e}"
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
        except Exception as e:
            self._init_error = f"nvmlDeviceGetCount failed: {e}"
            pynvml.nvmlShutdown()
            return
        if self.cfg.visible == "all":
            self.devices = list(range(count))
        else:
            self.devices = [i for i in self.cfg.visible if 0 <= i < count]
        self._nvml = pynvml
        if not self.devices:
            self._init_error = "нет видимых GPU-устройств"
        self.ready = bool(self.devices)

    # ------------------------------------------------------------------- poll
    def poll_sync(self) -> tuple[list[Sample], list[dict[str, Any]]]:
        """Блокирующий опрос (вызывается через asyncio.to_thread).

        Возвращает (samples, device_rows) — device_rows для автозаполнения
        ``gpu_devices`` при первом успешном опросе.
        """
        self._ensure_init()
        if not self.ready:
            raise GpuError(self._init_error or "NVML not ready")
        nvml = self._nvml
        now = int(time.time())
        samples: list[Sample] = []
        device_rows: list[dict[str, Any]] = []
        self._snapshot_gpus: dict[int, dict[str, Any]] = {}
        for idx in self.devices:
            h = nvml.nvmlDeviceGetHandleByIndex(idx)
            try:
                dev = _read_device(nvml, h)
            except Exception as e:  # устройство ушло в ошибку
                raise GpuError(f"GPU {idx}: {e}") from e
            device_rows.append(
                {
                    "id": idx,
                    "name": dev["name"],
                    "total_mem_mib": dev["mem_total_mib"],
                    "pci_bus": dev["pci_bus"],
                }
            )
            self._snapshot_gpus[idx] = {
                "id": idx,
                "name": dev["name"],
                "power_w": dev["power_w"],
                "power_limit_w": dev["power_limit_w"],
                "util": dev["util_pct"],
                "mem_used_mib": dev["mem_used_mib"],
                "mem_total_mib": dev["mem_total_mib"],
                "temp": dev["temp_c"],
                "sm_clock_mhz": dev["clock_sm_mhz"],
                "mem_clock_mhz": dev["clock_mem_mhz"],
                "throttle": dev["throttle_reasons"],
                "ecc_correctable": dev["ecc_correctable"],
                "ecc_uncorrectable": dev["ecc_uncorrectable"],
            }
            for key, metric in (
                ("power_w", "gpu_power"),
                ("util_pct", "gpu_util"),
                ("mem_used_mib", "gpu_mem_used_mib"),
                ("mem_total_mib", "gpu_mem_total_mib"),
                ("temp_c", "gpu_temp"),
                ("clock_sm_mhz", "gpu_clock_sm"),
                ("clock_mem_mhz", "gpu_clock_mem"),
                ("throttle_reasons", "gpu_throttle_reasons"),
                ("ecc_correctable", "gpu_ecc_correctable"),
                ("ecc_uncorrectable", "gpu_ecc_uncorrectable"),
            ):
                v = dev[key]
                if v is None:
                    continue  # поле недоступно — пропускаем (не 0!)
                samples.append(Sample(metric, now, float(v), "gpu", idx, None))
        self.last_snapshot = {"ts": now, "gpus": self._snapshot_gpus}
        return samples, device_rows

    async def poll(self) -> tuple[list[Sample], list[dict[str, Any]]]:
        import asyncio

        return await asyncio.to_thread(self.poll_sync)

    @staticmethod
    async def upsert_devices(conn, rows: list[dict[str, Any]]) -> None:
        """Автообнаружение: вставляем неизвестные устройства в gpu_devices."""
        for r in rows:
            await conn.execute(
                """INSERT INTO gpu_devices (id, name, total_mem_mib, pci_bus)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name,
                     total_mem_mib=excluded.total_mem_mib,
                     pci_bus=excluded.pci_bus""",
                (r["id"], r["name"], r["total_mem_mib"], r["pci_bus"]),
            )
        await conn.commit()


def _power_w(raw: float) -> float:
    """NVML GetPowerUsage формально в мкВт, но некоторые драйверы (580+) — в мВт.
    Ээврика: значения ≥10 МкВт — мкВт (обычный случай), иначе — мВт."""
    if raw >= 10_000_000:
        return raw / 1e6
    return raw / 1e3


def _clock_mhz(raw: float) -> float:
    """NVML GetClockInfo формально в кГц, но некоторые драйверы (580+) — в МГц.
    Ээврика: raw < 100_000 трактуем как уже МГц (кГц-значения всегда >> 100 МГц)."""
    if raw < 100_000:
        return raw
    return raw / 1000.0


def _read_device(nvml, handle) -> dict[str, Any]:
    """Снимок одной карты. Недоступные поля — None (не 0)."""
    d: dict[str, Any] = {}
    d["name"] = (_safe(nvml, nvml.nvmlDeviceGetName, handle) or "unknown").strip()
    d["pci_bus"] = _safe(nvml, nvml.nvmlDeviceGetPciInfo, handle, fmt=lambda p: p.busId)

    try:
        d["mem_total_mib"] = nvml.nvmlDeviceGetMemoryInfo(handle).total // (1024 * 1024)
    except Exception:
        d["mem_total_mib"] = None
    try:
        mem = nvml.nvmlDeviceGetMemoryInfo(handle)
        d["mem_used_mib"] = mem.used // (1024 * 1024)
    except Exception:
        d["mem_used_mib"] = None
    power_raw = _safe(nvml, nvml.nvmlDeviceGetPowerUsage, handle)
    d["power_w"] = _power_w(power_raw) if power_raw is not None else None
    try:
        d["util_pct"] = nvml.nvmlDeviceGetUtilizationRates(handle).gpu
    except Exception:
        d["util_pct"] = None
    d["temp_c"] = _safe(
        nvml, nvml.nvmlDeviceGetTemperature, handle, extra=(nvml.NVML_TEMPERATURE_GPU,)
    )
    # clocks (кГц/МГц — см. _clock_mhz)
    sm_raw = _safe(nvml, nvml.nvmlDeviceGetClockInfo, handle, extra=(nvml.NVML_CLOCK_SM,))
    d["clock_sm_mhz"] = _clock_mhz(sm_raw) if sm_raw is not None else None
    mem_raw = _safe(nvml, nvml.nvmlDeviceGetClockInfo, handle, extra=(nvml.NVML_CLOCK_MEM,))
    d["clock_mem_mhz"] = _clock_mhz(mem_raw) if mem_raw is not None else None
    d["throttle_reasons"] = _safe(nvml, nvml.nvmlDeviceGetCurrentClocksThrottleReasons, handle)
    # Лимит мощности (NVML PowerManagementLimit, мкВт; при ошибке — None)
    plim_raw = _safe(nvml, nvml.nvmlDeviceGetPowerManagementLimit, handle)
    d["power_limit_w"] = _power_w(plim_raw) if plim_raw is not None else None
    try:
        d["ecc_correctable"] = nvml.nvmlDeviceGetTotalEccErrors(
            handle, nvml.NVML_MEMORY_ERROR_CORRECTABLE
        )
    except Exception:
        d["ecc_correctable"] = None
    try:
        d["ecc_uncorrectable"] = nvml.nvmlDeviceGetTotalEccErrors(
            handle, nvml.NVML_MEMORY_ERROR_UNCORRECTABLE
        )
    except Exception:
        d["ecc_uncorrectable"] = None
    return d


def _safe(nvml, fn, handle, fmt=None, extra=()):
    try:
        v = fn(handle, *extra) if extra else fn(handle)
        return fmt(v) if fmt else v
    except Exception:
        return None
