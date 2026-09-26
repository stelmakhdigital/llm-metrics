"""Асинхронный доступ к SQLite (aiosqlite), WAL-режим."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

from .schema import SCHEMA_STATEMENTS


async def init_db(path: str) -> aiosqlite.Connection:
    """Открывает БД (создаёт файл/каталог), включает WAL, создаёт схему.

    Схема идемпотентна (IF NOT EXISTS) — это dev-bootstrap; для управления
    изменениями схемы используется Alembic (``api/migrations``).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(p))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    for stmt in SCHEMA_STATEMENTS:
        await conn.execute(stmt)
    await conn.commit()
    return conn


def rows_to_dicts(rows: list[aiosqlite.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
