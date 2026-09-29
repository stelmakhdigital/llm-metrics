"""Алерты: правила, конфиг из settings (F4.1).

Хранение: таблица ``settings``, ключ ``alert_rules``, value — JSON:

    {"enabled": true, "telegram_webhook": "https://…",
     "rules": [{"id": "kv_cache_high", "enabled": true, …}, …]}

Если ключ не задан (seed не делался) — используются правила по умолчанию
(:data:`DEFAULT_RULES`) + флаг/webhook из конфига ``alerts.*``.
Изменение правил из UI — PUT /api/settings/alerts (заменяет целиком,
без версионирования: это не данные, а настройки).

Семантика условия метрического правила (issue #6 — «длится», а не
«было где-то»): свежий замер не старше 180 с, последнее значение —
нарушение, **≥50% точек окна `for_s` — нарушение** и есть нарушение в
последних 120 с (единичный всплеск на 1 полл не алертит). Источник
оффлайн — правило с ``source``: статус ≠ online и сбой длится ≥ ``for_s``.
После восстановления правило не срабатывает повторно ``cooldown_s``.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields
from typing import Any

KEY = "alert_rules"

LEVELS = ("warning", "critical")
OPS = (">", "<")


@dataclass
class Rule:
    id: str
    title: str
    level: str = "warning"          # warning | critical
    metric: str | None = None       # метрика в metric_samples (None — источник)
    op: str | None = None           # ">" | "<"
    value: float | None = None      # порог
    source: str | None = None       # "vllm" | "gpu" | "system" (статус источника)
    for_s: int = 120                # нарушение должно длиться
    cooldown_s: int = 3600          # пауза после восстановления
    enabled: bool = True


#: Правила по умолчанию (seed и «сброс» в UI).
DEFAULT_RULES: list[Rule] = [
    Rule("src_vllm", "vLLM оффлайн", "critical", source="vllm", for_s=60, cooldown_s=300),
    Rule("src_gpu", "GPU-источник оффлайн", "warning", source="gpu", for_s=120, cooldown_s=600),
    Rule("src_system", "Системный источник оффлайн", "warning", source="system", for_s=120, cooldown_s=600),
    Rule(
        "kv_cache_high",
        "KV-кэш vLLM > 90%",
        "warning",
        metric="kv_cache_usage",
        op=">",
        value=90,
        for_s=300,
        cooldown_s=3600,
    ),
    Rule(
        "queue_high",
        "Очередь vLLM > 20 запросов",
        "warning",
        metric="num_requests_waiting",
        op=">",
        value=20,
        for_s=300,
        cooldown_s=3600,
    ),
    Rule(
        "ttft_high",
        "TTFT p95 > 120 с",
        "warning",
        metric="ttft_p95",
        op=">",
        value=120.0,
        for_s=300,
        cooldown_s=3600,
    ),
    Rule(
        "gpu_throttle",
        "GPU троттлинг",
        "warning",
        metric="gpu_throttle_reasons",
        op=">",
        value=0,
        for_s=300,
        cooldown_s=3600,
    ),
    Rule(
        "disk_high",
        "Диск / > 90%",
        "warning",
        metric="disk_used_pct|/",
        op=">",
        value=90,
        for_s=600,
        cooldown_s=3600,
    ),
]

_RULE_FIELDS = {f.name for f in fields(Rule)}


def rule_from_dict(d: dict[str, Any]) -> Rule:
    """Нормализует dict → Rule (неизвестные ключи игнорируются)."""
    known = {k: v for k, v in d.items() if k in _RULE_FIELDS}
    return Rule(**known)


def rules_to_payload(rules: list[Rule]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rules]


async def get_alert_cfg(db) -> dict[str, Any]:
    """{enabled, telegram_webhook, rules} — из settings (или пустой список)."""
    rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (KEY,))
    if not rows:
        return {}
    try:
        data = json.loads(rows[0]["value"])
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    rules: list[Rule] = []
    for r in data.get("rules") or []:
        if isinstance(r, dict) and r.get("id"):
            rules.append(rule_from_dict(r))
    return {
        "enabled": bool(data.get("enabled", True)),
        "telegram_webhook": data.get("telegram_webhook"),
        "rules": rules,
    }


async def seed_alert_cfg(db, *, enabled: bool, webhook: str | None) -> None:
    """Стартовое состояние из конфига + правила по умолчанию (идемпотентно)."""
    if await get_alert_cfg(db):
        return
    payload = {
        "enabled": enabled,
        "telegram_webhook": webhook,
        "rules": rules_to_payload(DEFAULT_RULES),
    }
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (KEY, json.dumps(payload), int(time.time())),
    )
    await db.commit()


async def set_alert_cfg(
    db,
    *,
    enabled: bool | None = None,
    telegram_webhook: str | None = None,
    rules: list[Rule] | None = None,
) -> dict[str, Any]:
    """Частичное обновление: неуказанные части берутся из текущего состояния."""
    current = await get_alert_cfg(db)
    new = {
        "enabled": enabled if enabled is not None else current.get("enabled", True),
        "telegram_webhook": (
            telegram_webhook
            if telegram_webhook is not None
            else current.get("telegram_webhook")
        ),
        "rules": rules if rules is not None else current.get("rules", DEFAULT_RULES),
    }
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (KEY, json.dumps(
            {
                "enabled": new["enabled"],
                "telegram_webhook": new["telegram_webhook"],
                "rules": rules_to_payload(new["rules"]),
            }
        ), int(time.time())),
    )
    await db.commit()
    return new


def effective_cfg(
    stored: dict[str, Any], *, default_enabled: bool, default_webhook: str | None
) -> dict[str, Any]:
    """Конфиг для движка: settings поверх дефолтов из конфига приложения."""
    if not stored:
        return {
            "enabled": default_enabled,
            "telegram_webhook": default_webhook,
            "rules": DEFAULT_RULES,
        }
    return {
        "enabled": stored.get("enabled", True),
        "telegram_webhook": stored.get("telegram_webhook") or default_webhook,
        "rules": stored.get("rules") or DEFAULT_RULES,
    }
