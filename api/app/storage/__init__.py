"""Хранилище: SQLite (WAL), схема по ТЗ §4, асинхронный доступ (aiosqlite)."""

from .db import init_db
from .schema import SCHEMA_STATEMENTS

__all__ = ["init_db", "SCHEMA_STATEMENTS"]
