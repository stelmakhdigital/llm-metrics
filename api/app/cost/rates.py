"""Версионирование тарифов (ТЗ §6, §7: GET/PUT /api/settings/cost).

Хранение: таблица ``settings``, ключ ``cost_rates``, value — JSON-массив
версий:

    [{"updated_at": 1756200000, "currency": "USD",
      "rate_per_kwh_usd": 0.10, "system_baseline_watts": 200,
      "token_prompt_per_million_usd": 0.5,
      "token_completion_per_million_usd": 1.5}, ...]

Порядок в массиве — хронологический (обновления = добавление новой версии,
старые не редактируются). При запросе периода используются тарифы,
активные на момент часа (cost engine).
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import Cost

KEY = "cost_rates"

# Поля версии (ключи JSON).
VERSION_FIELDS = (
    "currency",
    "rate_per_kwh_usd",
    "system_baseline_watts",
    "token_prompt_per_million_usd",
    "token_completion_per_million_usd",
)


def version_from_cost(cost: Cost) -> dict[str, Any]:
    """Версия тарифа из конфига ``cost.*`` (seed при старте)."""
    return {
        "updated_at": int(time.time()),
        "currency": cost.currency,
        "rate_per_kwh_usd": cost.electricity.rate_per_kwh_usd,
        "system_baseline_watts": cost.electricity.system_baseline_watts,
        "token_prompt_per_million_usd": cost.tokens.per_million_usd.get("prompt", 0.0),
        "token_completion_per_million_usd": cost.tokens.per_million_usd.get("completion", 0.0),
    }


def sanitize_version(v: dict[str, Any]) -> dict[str, Any]:
    """Нормализует версию: только известные ключи, числа — float."""
    out: dict[str, Any] = {
        "updated_at": int(v["updated_at"]),
        "currency": str(v.get("currency") or "USD"),
    }
    for f in VERSION_FIELDS[1:]:
        out[f] = float(v.get(f) or 0.0)
    return out


async def get_versions(db) -> list[dict[str, Any]]:
    """Массив версий (хронологический), пустой список если ещё не seed."""
    rows = await db.execute_fetchall(
        "SELECT value FROM settings WHERE key = ?", (KEY,)
    )
    if not rows:
        return []
    try:
        data = json.loads(rows[0]["value"])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    versions = [sanitize_version(v) for v in data if isinstance(v, dict)]
    versions.sort(key=lambda v: v["updated_at"])
    return versions


async def seed_cost_rates(db, cost: Cost) -> None:
    """Стартовая версия из конфига, если массив пуст (идемпотентно)."""
    if await get_versions(db):
        return
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (KEY, json.dumps([version_from_cost(cost)]), int(time.time())),
    )
    await db.commit()


async def add_version(db, overrides: dict[str, Any]) -> dict[str, Any]:
    """Новая версия = текущая + заданные поля; updated_at = now."""
    versions = await get_versions(db)
    base = versions[-1] if versions else version_from_cost(Cost())
    new = {**base, "updated_at": int(time.time())}
    for f in VERSION_FIELDS[1:]:
        if f in overrides and overrides[f] is not None:
            new[f] = str(overrides[f]) if f == "currency" else float(overrides[f])
    if not any(
        overrides.get(f) is not None for f in VERSION_FIELDS[1:]
    ):
        raise ValueError("не передано ни одно поле тарифа")
    versions.append(new)
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (KEY, json.dumps(versions), new["updated_at"]),
    )
    await db.commit()
    return new


async def get_settings_payload(db) -> dict[str, Any]:
    """GET /api/settings/cost: {current, history[]} — history: новые первыми."""
    versions = await get_versions(db)
    return {
        "current": versions[-1] if versions else None,
        "history": list(reversed(versions)),
    }


def rate_for_ts(versions: list[dict[str, Any]], ts: int) -> dict[str, Any]:
    """Версия, действовавшая на момент ``ts`` (после updated_at версии).

    Версии в хронологическом порядке; при совпадении updated_at —
    поздняя в списке. Если момент раньше первой версии — первая.
    """
    active = versions[0]
    for v in versions:
        if v["updated_at"] <= ts:
            active = v
        else:
            break
    return active
