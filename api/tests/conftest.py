"""Общие фикстуры: временная БД, приложение без poller'ов."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# app.main при импорте создаёт app (load_config из ENV) — VLLM_URL обязателен.
os.environ.setdefault("VLLM_URL", "http://127.0.0.1:8000")

from app.config import AppConfig, Sources, Storage  # noqa: E402
from app.main import create_app
from app.storage.db import init_db

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "metrics.db"


@pytest.fixture
async def db(db_path):
    conn = await init_db(str(db_path))
    yield conn
    await conn.close()


@pytest.fixture
def app_config(db_path):
    return AppConfig(
        sources=Sources(),
        storage=Storage(sqlite_path=str(db_path)),
        start_pollers=False,
    )


@pytest.fixture
def make_app(app_config):
    def _make(**overrides):
        cfg = AppConfig(
            sources=app_config.sources,
            storage=app_config.storage,
            cost=app_config.cost,
            start_pollers=overrides.pop("start_pollers", False),
        )
        return create_app(config=cfg, start_pollers=False)

    return _make


# Хелперы seed — в tests/util.py (импортируются для обратной совместимости)
from util import seed_log_entries, seed_samples, seed_samples_aio  # noqa: E402,F401


@pytest.fixture
def client(make_app, db_path):
    """FastAPI TestClient с приложением без poller'ов."""
    from fastapi.testclient import TestClient

    app = make_app()
    with TestClient(app) as c:
        yield c
