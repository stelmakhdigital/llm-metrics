"""Общие фикстуры: временная БД, приложение без poller'ов."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig, Sources, Storage
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


def seed_samples(db_path, rows, commit=True):
    """rows: (metric, ts, value, source, gpu, model) — синхронная запись
    через sqlite3 (для синхронных тестов агрегатора/ретенции, где БД не
    открыта асинхронно)."""
    import sqlite3

    c = sqlite3.connect(str(db_path))
    c.executemany(
        """INSERT INTO metric_samples (metric, ts, value, source, gpu, model)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    c.commit()
    c.close()


async def seed_samples_aio(db, rows) -> None:
    """То же самое, но через aiosqlite-коннект (async-тесты)."""
    await db.executemany(
        """INSERT INTO metric_samples (metric, ts, value, source, gpu, model)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    await db.commit()


def seed_log_entries(db_path, rows, commit=True):
    """rows: (ts_ms, level, line, source) — синхронная запись log_entries."""
    import sqlite3

    c = sqlite3.connect(str(db_path))
    c.executemany(
        "INSERT INTO log_entries (ts, level, line, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    if commit:
        c.commit()
    c.close()
