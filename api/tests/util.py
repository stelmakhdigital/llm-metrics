"""Общие хелперы тестов (seed-запись в БД)."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def seed_samples(db_path: Path, rows, commit: bool = True) -> None:
    """rows: (metric, ts, value, source, gpu, model) — синхронная запись
    через sqlite3."""
    c = sqlite3.connect(str(db_path))
    c.executemany(
        """INSERT INTO metric_samples (metric, ts, value, source, gpu, model)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    if commit:
        c.commit()
    c.close()


async def seed_samples_aio(db, rows) -> None:
    """То же, но через aiosqlite-коннект (async-тесты)."""
    await db.executemany(
        """INSERT INTO metric_samples (metric, ts, value, source, gpu, model)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    await db.commit()


def seed_log_entries(db_path: Path, rows, commit: bool = True) -> None:
    """rows: (ts_ms, level, line, source)."""
    c = sqlite3.connect(str(db_path))
    c.executemany(
        "INSERT INTO log_entries (ts, level, line, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    if commit:
        c.commit()
    c.close()
