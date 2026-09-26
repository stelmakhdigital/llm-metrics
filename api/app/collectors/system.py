"""Коллектор системных метрик (psutil + /proc/pressure), ТЗ §3.1/§5.4.

Метрики (source='system', gpu=NULL):
* CPU: ``cpu_usage`` (общий %), ``cpu_usage_core_{i}``, ``cpu_steal_pct``,
  ``cpu_freq_mhz``, ``load_avg_1``/``load_avg_5``/``load_avg_15``;
* RAM: ``ram_total_mb``, ``ram_used_mb``, ``ram_available_mb``,
  ``swap_used_mb``;
* Диски: ``disk_used_pct|<mount>`` (занятость по mount-ам),
  ``disk_read_mb_s``/``disk_write_mb_s`` (И/В по всем дискам, из дельт);
* Сеть: ``net_rx_mbps``/``net_tx_mbps`` — по основному интерфейсу
  (первый с IPv4, кроме lo);
* PSI: ``psi_{cpu,memory,io}_avg{10,60,300}`` из ``/proc/pressure/*``
  (колонка ``some``).

Пропускает то, что недоступно (None), — разрывы вместо нулей (ТЗ §8.2).
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path
from typing import Any

import psutil

from .vllm import Sample

__all__ = ["SystemCollector"]

_REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs"}
_PSI_FILES = {
    "cpu": Path("/proc/pressure/cpu"),
    "memory": Path("/proc/pressure/memory"),
    "io": Path("/proc/pressure/io"),
}


class SystemCollector:
    def __init__(self):
        self._prev_disk_io: tuple[float, int, int] | None = None  # (ts, read, write)
        self._prev_net_io: tuple[float, int, int] | None = None  # (ts, rx, tx)
        self._prev_cpu_times: list[Any] | None = None
        self._iface: str | None = None
        self._cores: int = 0
        # Кэш последнего снимка (F1, docs/api-contracts.md):
        # {"ts", "metrics": {имя: значение}}
        self.last_snapshot: dict | None = None

    # ------------------------------------------------------------------ warm
    def warmup(self) -> None:
        """Первый запуск psutil-счётчиков (иначе первый cpu% = 0)."""
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(percpu=True, interval=None)
        self._cores = psutil.cpu_count(logical=True) or 0
        self._iface = _primary_iface()
        self._prev_cpu_times = [tuple(t) for t in psutil.cpu_times(percpu=True)]
        self._prev_disk_io = self._disk_io()
        self._prev_net_io = self._net_io()

    async def poll(self) -> list[Sample]:
        return await asyncio.to_thread(self.poll_sync)

    # ------------------------------------------------------------------ poll
    def poll_sync(self) -> list[Sample]:
        now = int(time.time())
        s: list[Sample] = []
        add = lambda m, v: s.append(Sample(m, now, float(v), "system", None, None))  # noqa: E731

        # CPU
        add("cpu_usage", psutil.cpu_percent(interval=None))
        for i, v in enumerate(psutil.cpu_percent(percpu=True, interval=None)):
            add(f"cpu_usage_core_{i}", v)
        freq = psutil.cpu_freq()
        if freq is not None and freq.current:
            add("cpu_freq_mhz", freq.current)
        steal = self._steal_pct()
        if steal is not None:
            add("cpu_steal_pct", steal)
        try:
            l1, l5, l15 = os.getloadavg()
            add("load_avg_1", l1)
            add("load_avg_5", l5)
            add("load_avg_15", l15)
        except OSError:
            pass

        # RAM / swap
        vm = psutil.virtual_memory()
        add("ram_total_mb", vm.total / 1e6)
        add("ram_used_mb", vm.used / 1e6)
        add("ram_available_mb", vm.available / 1e6)
        sw = psutil.swap_memory()
        add("swap_used_mb", sw.used / 1e6)

        # Диски: занятость по mount'ам
        try:
            for part in psutil.disk_partitions(all=False):
                if part.fstype.lower() not in _REAL_FS:
                    continue
                mount = part.mountpoint
                if not mount or mount.startswith(("/proc", "/sys", "/dev", "/snap")):
                    continue
                try:
                    used = psutil.disk_usage(mount).percent
                except OSError:
                    continue
                add(f"disk_used_pct|{mount}", used)
        except Exception:
            pass

        # Диски: И/В (дельты по всем дискам)
        dio = self._disk_io()
        if dio is not None:
            ts, r, w = dio
            if self._prev_disk_io is not None:
                pts, pr, pw = self._prev_disk_io
                dt = ts - pts
                if dt > 0 and r >= pr and w >= pw:
                    add("disk_read_mb_s", (r - pr) / dt / 1e6)
                    add("disk_write_mb_s", (w - pw) / dt / 1e6)
            self._prev_disk_io = dio

        # Сеть: основной интерфейс
        nio = self._net_io()
        if nio is not None:
            ts, rx, tx = nio
            if self._prev_net_io is not None:
                pts, prx, ptx = self._prev_net_io
                dt = ts - pts
                if dt > 0 and rx >= prx and tx >= ptx:
                    add("net_rx_mbps", (rx - prx) / dt / 1e5)  # Б/с → Мбит/с
                    add("net_tx_mbps", (tx - ptx) / dt / 1e5)
            self._prev_net_io = nio

        # PSI
        for kind, path in _PSI_FILES.items():
            vals = _read_psi(path)
            for suffix, v in (
                ("avg10", vals.get("avg10")),
                ("avg60", vals.get("avg60")),
                ("avg300", vals.get("avg300")),
            ):
                if v is not None:
                    add(f"psi_{kind}_{suffix}", v)
        self.last_snapshot = {"ts": now, "metrics": {x.metric: x.value for x in s}}
        return s

    # -------------------------------------------------------------- internal
    def _steal_pct(self) -> float | None:
        """Steal % по дельте /proc-времён (psutil cpu_times percpu)."""
        try:
            cur = psutil.cpu_times(percpu=True)
        except Exception:
            return None
        if self._prev_cpu_times is None or len(cur) != len(self._prev_cpu_times):
            self._prev_cpu_times = list(cur)
            return None
        steal_d, total_d = 0.0, 0.0
        for old, new in zip(self._prev_cpu_times, cur):
            old_t = tuple(old)
            new_t = tuple(new)
            fields = new._fields if hasattr(new, "_fields") else old._fields
            o = dict(zip(fields, old_t))
            n = dict(zip(fields, new_t))
            steal_d += max(0.0, n.get("steal", 0.0) - o.get("steal", 0.0))
            total_d += sum(max(0.0, n[k] - o[k]) for k in fields)
        self._prev_cpu_times = list(cur)
        if total_d <= 0:
            return None
        return 100.0 * steal_d / total_d

    def _disk_io(self) -> tuple[float, int, int] | None:
        try:
            c = psutil.disk_io_counters()
            if c is None:
                return None
            return (time.time(), int(c.read_bytes), int(c.write_bytes))
        except Exception:
            return None

    def _net_io(self) -> tuple[float, int, int] | None:
        iface = self._iface or _primary_iface()
        if iface is None:
            return None
        self._iface = iface
        try:
            c = psutil.net_io_counters(pernic=True).get(iface)
            if c is None:
                return None
            return (time.time(), int(c.bytes_recv), int(c.bytes_sent))
        except Exception:
            return None


def _primary_iface() -> str | None:
    """Первый интерфейс с IPv4-адресом, кроме loopback."""
    try:
        for name, addrs in psutil.net_if_addrs().items():
            if name == "lo":
                continue
            if any(a.family == socket.AF_INET and a.address for a in addrs):
                return name
    except Exception:
        return None
    return None


def _read_psi(path: Path) -> dict[str, float | None]:
    """``some avg10=.. avg60=.. avg300=..`` → {"10": x, "60": y, "300": z}."""
    out: dict[str, float | None] = {"avg10": None, "avg60": None, "avg300": None}
    try:
        line = path.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("some "):
            return out
        for part in line[len("some ") :].split():
            k, _, v = part.partition("=")
            if k in out:
                try:
                    out[k] = float(v)
                except ValueError:
                    pass
    except OSError:
        pass
    return out
