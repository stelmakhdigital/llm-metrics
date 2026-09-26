"""Обвязка poller-ов: цикл опроса, статусы источников, запись выборок.

Инвариант (ТЗ §3.1): сбой одного источника не роняет сбор остальных —
каждый poller — отдельная задача со своей обработкой ошибок и статусом.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .vllm import Sample

log = logging.getLogger(__name__)

__all__ = ["SourceStatus", "SourceRegistry", "poll_loop", "insert_samples"]

SampleList = list[Sample]
# poller возвращает список выборок или (выборки, device_rows для gpu_devices)
PollResult = SampleList | tuple[SampleList, list[dict[str, Any]]]


@dataclass
class SourceStatus:
    name: str
    status: str = "unknown"  # unknown | online | offline
    last_ok_ts: float | None = None
    last_poll_ts: float | None = None
    last_error: str | None = None

    def ok(self, ts: float | None = None) -> None:
        ts = ts if ts is not None else time.time()
        self.status = "online"
        self.last_ok_ts = ts
        self.last_poll_ts = ts
        self.last_error = None

    def fail(self, err: str, ts: float | None = None) -> None:
        ts = ts if ts is not None else time.time()
        self.status = "offline"
        self.last_poll_ts = ts
        self.last_error = err[:500]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_ok_ts": self.last_ok_ts,
            "last_poll_ts": self.last_poll_ts,
            "last_error": self.last_error,
        }


class SourceRegistry:
    def __init__(self, names: tuple[str, ...] = ("vllm", "gpu", "system")):
        self._statuses: dict[str, SourceStatus] = {n: SourceStatus(n) for n in names}

    def __getitem__(self, name: str) -> SourceStatus:
        return self._statuses[name]

    def all(self) -> dict[str, SourceStatus]:
        return dict(self._statuses)

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {n: s.to_dict() for n, s in self._statuses.items()}


async def wait_cancelable(event: asyncio.Event, delay: float) -> None:
    """Sleep, прерываемый stop-событием (быстрый shutdown)."""
    try:
        await asyncio.wait_for(event.wait(), timeout=max(0.0, delay))
    except asyncio.TimeoutError:
        pass


async def insert_samples(conn, samples: SampleList) -> int:
    """Пакетная запись выборок в metric_samples."""
    if not samples:
        return 0
    await conn.executemany(
        """INSERT INTO metric_samples (metric, ts, value, gpu, source, model)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(s.metric, s.ts, s.value, s.gpu, s.source, s.model) for s in samples],
    )
    await conn.commit()
    return len(samples)


async def poll_loop(
    name: str,
    interval: float,
    poll_once: Callable[[], Awaitable[PollResult]],
    statuses: SourceRegistry,
    conn,
    stop: asyncio.Event,
    on_devices: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
) -> None:
    """Бесконечный цикл опроса одного источника.

    Любая ошибка poll-а фиксируется в статусе источника, цикл продолжается —
    падение источника не останавливает приложение (ТЗ §8.2).
    """
    log.info("poller %s started (interval %.1fs)", name, interval)
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            result = await poll_once()
            if isinstance(result, tuple):
                samples, device_rows = result
            else:
                samples, device_rows = result, None
            if samples:
                await insert_samples(conn, samples)
            if device_rows and on_devices is not None:
                await on_devices(device_rows)
            statuses[name].ok()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — сбой источника не роняет остальное
            statuses[name].fail(f"{type(e).__name__}: {e}")
            log.warning("poller %s: %s", name, e)
        if stop.is_set():
            break
        await wait_cancelable(stop, interval - (time.monotonic() - t0))
    log.info("poller %s stopped", name)
