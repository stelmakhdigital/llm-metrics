"""Загрузка и валидация конфигурации (YAML, ТЗ §3.3).

Путь к файлу: переменная окружения ``METRICS_CONFIG``, по умолчанию
``metrics.config.yaml`` в текущем каталоге.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

ENV_CONFIG = "METRICS_CONFIG"
DEFAULT_CONFIG_PATH = "metrics.config.yaml"


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
    sqlite_path: str = "./data/metrics.db"
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


class Sources(BaseModel):
    vllm: VllmSource = VllmSource()
    gpus: GpuSource = GpuSource()
    system: SystemSource = SystemSource()
    logs: LogSources = LogSources()


class AppConfig(BaseModel):
    sources: Sources = Sources()
    storage: Storage = Storage()
    cost: Cost = Cost()
    # dev-режим: не запускать pollers (используется в тестах)
    start_pollers: bool = True

    def db_url(self) -> str:
        """SQLAlchemy URL для alembic (sqlite:////абс_путь)."""
        return "sqlite:///" + str(Path(self.storage.sqlite_path).resolve())


def load_config(path: str | None = None) -> AppConfig:
    """Читает YAML и валидирует в :class:`AppConfig`.

    Если файл не найден — используется конфигурация по умолчанию
    (и предупреждение в stdout не требуется: это dev-режим).
    """
    if path is None:
        path = os.environ.get(ENV_CONFIG, DEFAULT_CONFIG_PATH)
    p = Path(path)
    if not p.is_file():
        return AppConfig()
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Конфиг {p}: ожидается mapping верхнего уровня")
    return AppConfig.model_validate(data)
