"""Точка входа: FastAPI-приложение (uvicorn app.main:app).

Состав F0:
* storage — SQLite (WAL), схема §4;
* pollers — vLLM (5с), GPU (10с), system (10с) — чистый asyncio,
  каждый в отдельной задаче, сбой источника не роняет остальные;
* агрегатор — hourly/daily + токены + ретенция, цикл раз в 5 минут;
* API — /api/health, /api/metrics/{metric}, /api/overview, /api/gpus,
  /api/system, /api/model, /api/live (SSE, кэш снимков коллекторов).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI

from . import __version__
from .aggregator import Aggregator
from .alerts.engine import AlertEngine
from .alerts.rules import seed_alert_cfg
from .api.alerts_routes import router as alerts_router
from .api.cost import router as cost_router
from .api.routes import router
from .api.logs_routes import router as logs_router
from .api.settings import router as settings_router
from .collectors.base import SourceRegistry, poll_loop, wait_cancelable
from .collectors.gpu import GpuCollector
from .collectors.system import SystemCollector
from .collectors.vllm import VllmCollector
from .config import AppConfig, load_config
from .cost.rates import seed_cost_rates
from .logs.tailer import LogLineBuffer, LogTailer
from .storage.db import init_db

log = logging.getLogger(__name__)

AGGREGATOR_INTERVAL_S = 300


def create_app(
    config: AppConfig | None = None,
    start_pollers: bool | None = None,
) -> FastAPI:
    """Фабрика приложения (в тестах — с ``start_pollers=False``)."""
    cfg = config or load_config()
    run_pollers = cfg.start_pollers if start_pollers is None else start_pollers

    app = FastAPI(title="llm-metrics api", version=__version__)
    app.state.config = cfg
    app.include_router(router)
    app.include_router(cost_router)
    app.include_router(settings_router)
    app.include_router(logs_router)
    app.include_router(alerts_router)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = await init_db(cfg.storage.sqlite_path)
        app.state.db = db
        await seed_cost_rates(db, cfg.cost)  # тарифы: стартовая версия из конфига (F2)
        await seed_alert_cfg(
            db, enabled=cfg.alerts.enabled, webhook=cfg.alerts.telegram_webhook
        )  # алерты: стартовое состояние из конфига (F4)
        app.state.statuses = SourceRegistry(
            ("vllm", "gpu", "system")
            + tuple(f"logs.{s.name}" for s in cfg.sources.logs.sources)
        )
        app.state.http = httpx.AsyncClient(
            # Без переиспользования keep-alive: vLLM-сервер закрывает idle-
            # соединения (soak: ~каждый 3-й poll «Server disconnected»),
            # повторное использование такого соединения роняет выборку
            limits=httpx.Limits(max_keepalive_connections=0)
        )
        # Движок алертов (F4): правила по БД/статусам, Telegram-webhook, журнал
        app.state.alerts_engine = AlertEngine(
            db,
            app.state.statuses,
            app.state.http,
            default_enabled=cfg.alerts.enabled,
            default_webhook=cfg.alerts.telegram_webhook,
            check_interval_s=cfg.alerts.check_interval_s,
        )
        app.state.gpu_collector = None
        # Кэш последних снимков коллекторов (F1): единая точка чтения для
        # SSE /api/live и API — без SQL (docs/api-contracts.md)
        app.state.snapshots: dict[str, dict | None] = {
            "vllm": None,
            "gpu": None,
            "system": None,
        }
        app.state.started_at = time.time()
        stop = asyncio.Event()
        app.state.stop = stop
        tasks: list[asyncio.Task] = []
        # Буфер последних log-строк (ring ≤5000) для SSE /api/logs/live (F3)
        app.state.log_buffer = LogLineBuffer()

        if run_pollers:
            vllm_c = VllmCollector(cfg.sources.vllm)
            gpu_c = GpuCollector(cfg.sources.gpus)
            sys_c = SystemCollector()
            app.state.gpu_collector = gpu_c
            # «Прогрев» счётчиков psutil (иначе первый замер = 0)
            await asyncio.to_thread(_prime_psutil, sys_c)

            async def vllm_poll():
                samples = await vllm_c.poll(app.state.http)
                app.state.snapshots["vllm"] = vllm_c.last_snapshot
                return samples

            async def gpu_poll():
                result = await gpu_c.poll()
                app.state.snapshots["gpu"] = gpu_c.last_snapshot
                return result

            async def system_poll():
                samples = await sys_c.poll()
                app.state.snapshots["system"] = sys_c.last_snapshot
                return samples

            async def on_devices(rows):
                await GpuCollector.upsert_devices(db, rows)

            tasks.append(
                asyncio.create_task(
                    poll_loop(
                        "vllm",
                        cfg.sources.vllm.poll_seconds,
                        vllm_poll,
                        app.state.statuses,
                        db,
                        stop,
                    )
                )
            )
            tasks.append(
                asyncio.create_task(
                    poll_loop(
                        "gpu",
                        cfg.sources.gpus.poll_seconds,
                        gpu_poll,
                        app.state.statuses,
                        db,
                        stop,
                        on_devices=on_devices,
                    )
                )
            )
            tasks.append(
                asyncio.create_task(
                    poll_loop(
                        "system",
                        cfg.sources.system.poll_seconds,
                        system_poll,
                        app.state.statuses,
                        db,
                        stop,
                    )
                )
            )
            agg = Aggregator(db, cfg.storage.retention)

            # Алерты (F4): цикл проверки правил (запускать вместе с poller'ами,
            # без данных условия бессмысленны; тесты — start_pollers=False)
            await app.state.alerts_engine.restore()
            tasks.append(
                asyncio.create_task(app.state.alerts_engine.run(stop))
            )

            async def agg_loop():
                while not stop.is_set():
                    await wait_cancelable(stop, AGGREGATOR_INTERVAL_S)
                    if stop.is_set():
                        break
                    try:
                        await agg.run_cycle()
                    except Exception:  # noqa: BLE001
                        log.exception("aggregator cycle failed")

            tasks.append(asyncio.create_task(agg_loop()))

            # Log-tailer (F3): file-tail / docker logs, цикл раз в poll_seconds
            if cfg.sources.logs.sources:
                tailer = LogTailer(
                    cfg.sources.logs, db, app.state.statuses, app.state.log_buffer
                )
                tasks.append(asyncio.create_task(tailer.run(stop)))

        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await app.state.http.aclose()
            await db.close()

    app.router.lifespan_context = lifespan
    return app


def _prime_psutil(sys_c: SystemCollector) -> None:
    """Первый запуск счётчиков psutil в рабочем потоке (быстро)."""
    try:
        sys_c.warmup()
        import psutil

        for p in psutil.process_iter():
            try:
                p.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:  # noqa: BLE001
        log.warning("psutil warmup failed: %s", e)


class _JsonFormatter(logging.Formatter):
    """Одна JSON-строка на запись: {ts, level, logger, msg} (F5.5)."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage().replace("\n", " ")
        return json.dumps(
            {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": msg,
            },
            ensure_ascii=False,
        )


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


_setup_logging()
app = create_app()
