"""Загрузка и валидация конфигурации (F5.4: только ENV, без YAML).

Все параметры задаются переменными окружения (ТЗ §3.3). Обязательна
только ``VLLM_URL``; остальные имеют дефолты, см. :func:`load_config`.
"""

from __future__ import annotations

import os
from pathlib import Path

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class VllmSource(BaseModel):
    url: str = "http://127.0.0.1:8000"
    metrics_path: str = "/metrics"
    poll_seconds: float = 5
    # Необязательная статичная подпись модели; иначе берётся из лейблов model_name
    model_name: str | None = None
    request_timeout: float = 5


class GpuSource(BaseModel):
    poll_seconds: float = 10
    # all или список индексов
    visible: list[int] | Literal["all"] = "all"


class SystemSource(BaseModel):
    poll_seconds: float = 10


class LogSource(BaseModel):
    name: str
    type: Literal["file", "docker"] = "file"
    path: str | None = None
    container: str | None = None

    @field_validator("path")
    @classmethod
    def _path_for_file(cls, v: str | None, info) -> str | None:
        if info.data.get("type") == "file" and not v:
            raise ValueError("path обязателен для источника type=file")
        return v


class LogSources(BaseModel):
    sources: list[LogSource] = []
    poll_seconds: float = Field(default=1, gt=0)
    # Ретенция log_entries, дней (ТЗ §5.6, default 14); ежечасная чистка
    retention_days: int = Field(default=14, ge=1, le=365)


class Retention(BaseModel):
    raw_hours: int = 168
    hourly_days: int = 180
    daily_days: int | None = None  # None — безлимитно


class Storage(BaseModel):
    sqlite_path: str = "/data/metrics.db"
    retention: Retention = Retention()


class TokenRates(BaseModel):
    per_million_usd: dict[str, float] = Field(
        default_factory=lambda: {"prompt": 0.5, "completion": 1.5}
    )


class Electricity(BaseModel):
    rate_per_kwh_usd: float = 0.10
    system_baseline_watts: float = 200


class Cost(BaseModel):
    currency: str = "USD"
    electricity: Electricity = Electricity()
    tokens: TokenRates = TokenRates()


class Alerts(BaseModel):
    """Алерты (F4.1, ТЗ §3.3): вкл/выкл, Telegram-webhook, период проверки."""

    enabled: bool = True
    # Полный URL Telegram webhook (…/bot<TOKEN>/sendMessage?chat_id=…)
    telegram_webhook: str | None = None
    check_interval_s: int = Field(30, ge=5, le=600)


class Sources(BaseModel):
    vllm: VllmSource = VllmSource()
    gpus: GpuSource = GpuSource()
    system: SystemSource = SystemSource()
    logs: LogSources = LogSources()


class AppConfig(BaseModel):
    sources: Sources = Sources()
    storage: Storage = Storage()
    cost: Cost = Cost()
    alerts: Alerts = Alerts()
    # dev-режим: не запускать pollers (используется в тестах)
    start_pollers: bool = True

    def db_url(self) -> str:
        """SQLAlchemy URL для alembic (sqlite:////абс_путь)."""
        return "sqlite:///" + str(Path(self.storage.sqlite_path).resolve())


def _env(name: str, default: str = "") -> str:
    """Значение env-переменной (strip + inline-комментарий; пусто → default).

    Docker compose ``env_file`` НЕ режет inline-комментарии
    (``KEY=value # коммент`` → значение с ``# коммент``), а ведущие пробелы
    значения убирает — поэтому: значение, начинающееся с ``#`` (или с пробелом
    перед которым стоит ``#``) — мусор из .env, отбрасываем. Значения наших
    переменных никогда не содержат ``#``.
    """
    val = os.environ.get(name, "").strip()
    if val.startswith("#"):
        return default
    if " #" in val:
        val = val.split(" #", 1)[0].strip()
    return val or default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name}: ожидается число, получено {raw!r}") from None


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name}: ожидается целое, получено {raw!r}") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name}: ожидается true/false, получено {raw!r}")


def _env_gpu_visible() -> list[int] | Literal["all"]:
    """GPU_VISIBLE: ``all`` (дефолт) или список индексов, например ``0,1``."""
    raw = _env("GPU_VISIBLE", "all").lower()
    if raw == "all":
        return "all"
    try:
        indices = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise ValueError(
            f"GPU_VISIBLE: ожидается 'all' или список индексов (0,1), получено {raw!r}"
        ) from None
    return indices


def _env_telegram_webhook() -> str | None:
    """TELEGRAM_WEBHOOK из env; если пуст — docker secret /run/secrets/telegram_webhook."""
    raw = _env("TELEGRAM_WEBHOOK")
    if raw:
        return raw
    secret = Path("/run/secrets/telegram_webhook")
    if secret.is_file():
        return secret.read_text(encoding="utf-8").strip() or None
    return None


def load_config() -> AppConfig:
    """Собирает :class:`AppConfig` из переменных окружения.

    Обязательна только ``VLLM_URL``; остальные параметры берут дефолты.
    """
    vllm_url = _env("VLLM_URL")
    if not vllm_url:
        raise RuntimeError(
            "VLLM_URL не задана: укажите адрес vLLM-сервера, "
            "например VLLM_URL=http://vllm:8000"
        )
    daily_days = _env("RETENTION_DAILY_DAYS").strip()

    return AppConfig(
        sources=Sources(
            vllm=VllmSource(
                url=vllm_url,
                metrics_path=_env("VLLM_METRICS_PATH", "/metrics"),
                poll_seconds=_env_float("VLLM_POLL_S", 5),
                model_name=_env("VLLM_MODEL_NAME") or None,
                request_timeout=_env_float("VLLM_TIMEOUT_S", 5),
            ),
            gpus=GpuSource(
                poll_seconds=_env_float("GPU_POLL_S", 10),
                visible=_env_gpu_visible(),
            ),
            system=SystemSource(poll_seconds=_env_float("SYS_POLL_S", 10)),
            logs=LogSources(
                sources=[
                    LogSource(
                        name=_env("LOG_SOURCE_NAME", "vllm"),
                        type=_env("LOG_SOURCE_TYPE", "file"),
                        path=_env("LOG_SOURCE_PATH", "/var/log/vllm/vllm.log") or None,
                        container=_env("LOG_SOURCE_CONTAINER", "vllm") or None,
                    )
                ],
                poll_seconds=_env_float("LOG_POLL_S", 1),
                retention_days=_env_int("LOG_RETENTION_DAYS", 14),
            ),
        ),
        storage=Storage(
            sqlite_path=_env("SQLITE_PATH", "/data/metrics.db"),
            retention=Retention(
                raw_hours=_env_int("RETENTION_RAW_HOURS", 168),
                hourly_days=_env_int("RETENTION_HOURLY_DAYS", 180),
                daily_days=int(daily_days) if daily_days.strip() else None,
            ),
        ),
        cost=Cost(
            currency=_env("CURRENCY", "USD"),
            electricity=Electricity(
                rate_per_kwh_usd=_env_float("RATE_PER_KWH_USD", 0.10),
                system_baseline_watts=_env_float("BASELINE_WATTS", 200),
            ),
            tokens=TokenRates(
                per_million_usd={
                    "prompt": _env_float("PROMPT_PRICE_PER_M", 0.5),
                    "completion": _env_float("COMPLETION_PRICE_PER_M", 1.5),
                }
            ),
        ),
        alerts=Alerts(
            enabled=_env_bool("ALERTS_ENABLED", True),
            telegram_webhook=_env_telegram_webhook(),
            check_interval_s=_env_int("ALERTS_INTERVAL_S", 30),
        ),
    )
