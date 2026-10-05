"""Алерты API (F4.1): журнал + центр уведомлений + настройки.

* GET  /api/alerts            — активные + последние события
* POST /api/alerts/test       — тестовое Telegram-уведомление
* GET  /api/settings/alerts   — {enabled, telegram_webhook, webhook_configured, rules}
* PUT  /api/settings/alerts   — частичное обновление (enabled/webhook/rules)
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ..alerts.rules import (
    DEFAULT_RULES,
    LEVELS,
    Rule,
    get_alert_cfg,
    rules_to_payload,
    set_alert_cfg,
)

router = APIRouter()


def _engine(request: Request):
    return request.app.state.alerts_engine


def _default_cfg(request: Request) -> tuple[bool, str | None]:
    cfg = request.app.state.config.alerts
    return cfg.enabled, cfg.telegram_webhook


def _rules_from_body(items: list[AlertRuleIn]) -> list[Rule]:
    out: list[Rule] = []
    seen: set[str] = set()
    for r in items:
        if r.id in seen:
            raise HTTPException(400, f"Дубликат правила {r.id}")
        seen.add(r.id)
        out.append(
            Rule(
                id=r.id,
                title=r.title,
                level=r.level,
                metric=r.metric,
                op=r.op,
                value=r.value,
                source=r.source,
                for_s=r.for_s,
                cooldown_s=r.cooldown_s,
                enabled=r.enabled,
                webhook=r.webhook,
            )
        )
    return out


class AlertRuleIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    level: str = "warning"
    metric: str | None = None
    op: str | None = None
    value: float | None = None
    source: str | None = None
    for_s: int = Field(120, ge=0, le=86400)
    cooldown_s: int = Field(3600, ge=0, le=7 * 86400)
    enabled: bool = True
    webhook: str | None = None  # per-rule Telegram-webhook (None — глобальный)

    @field_validator("level")
    @classmethod
    def _level(cls, v: str) -> str:
        if v not in LEVELS:
            raise ValueError(f"level: {'|'.join(LEVELS)}")
        return v

    @field_validator("op")
    @classmethod
    def _op(cls, v: str | None) -> str | None:
        if v is not None and v not in (">", "<"):
            raise ValueError("op: '>' или '<'")
        return v

    @field_validator("source")
    @classmethod
    def _source(cls, v: str | None) -> str | None:
        if v is not None and v not in ("vllm", "gpu", "system"):
            raise ValueError("source: vllm | gpu | system")
        return v


class AlertsUpdate(BaseModel):
    enabled: bool | None = None
    telegram_webhook: str | None = None
    rules: list[AlertRuleIn] | None = None
    reset_rules: bool = False  # вернуть правила по умолчанию


@router.get("/api/alerts")
async def alerts_list(request: Request, limit: int = 100) -> dict:
    """{active: [...], recent: [...]} — recent: новые первыми (≤200)."""
    limit = max(1, min(limit, 200))
    db = request.app.state.db
    active = _engine(request).active()
    rows = await db.execute_fetchall(
        "SELECT id, rule, level, status, message, triggered_at, resolved_at "
        "FROM alerts ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    recent = [
        {
            "id": r["id"],
            "rule": r["rule"],
            "level": r["level"],
            "status": r["status"],
            "message": r["message"],
            "triggered_at": r["triggered_at"],
            "resolved_at": r["resolved_at"],
        }
        for r in rows
    ]
    return {"active": active, "recent": recent}


@router.post("/api/alerts/test")
async def alerts_test(request: Request):
    """Отправить тестовое сообщение в заданный webhook."""
    stored = await get_alert_cfg(request.app.state.db)
    # webhook: из settings, иначе из конфига
    webhook = (stored or {}).get("telegram_webhook") or _default_cfg(request)[1]
    ok, msg = await _engine(request).send_test(webhook)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


@router.get("/api/settings/alerts")
async def alerts_settings_get(request: Request) -> dict:
    stored = await get_alert_cfg(request.app.state.db)
    enabled, cfg_webhook = _default_cfg(request)
    if stored:
        final_webhook = stored.get("telegram_webhook") or cfg_webhook
        enabled = stored.get("enabled", enabled)
        rules = stored.get("rules")
    else:
        final_webhook = cfg_webhook
        rules = None
    return {
        "enabled": bool(enabled),
        "telegram_webhook": final_webhook or "",
        "webhook_configured": bool(final_webhook),
        "web_base_url": os.environ.get("WEB_BASE_URL") or "",
        "rules": rules_to_payload(rules) if rules else rules_to_payload(DEFAULT_RULES),
    }


@router.put("/api/settings/alerts")
async def alerts_settings_put(request: Request, body: AlertsUpdate):
    db = request.app.state.db
    if body.reset_rules:
        rules = DEFAULT_RULES
    elif body.rules is not None:
        rules = _rules_from_body(body.rules)
    else:
        rules = None
    webhook = body.telegram_webhook
    if webhook is not None:
        webhook = webhook.strip() or None
    await set_alert_cfg(
        db,
        enabled=body.enabled,
        telegram_webhook=webhook,
        rules=rules,
    )
    return {"updated_at": int(time.time())}
