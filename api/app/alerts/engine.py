"""Движок алертов (F4.1).

Фоновая задача: раз в ``check_interval_s`` вычисляет условия правил
(по ``metric_samples`` и статусам источников), ведёт журнал в таблице
``alerts`` и шлёт Telegram-уведомления (trigger / resolved), если
задач webhook. Сбой отправки не влияет на работу движка.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from ..collectors.base import SourceRegistry, wait_cancelable
from .rules import Rule, effective_cfg, get_alert_cfg

log = logging.getLogger(__name__)

#: Данные старше — считаются несвежими (условие = False, не алерт).
STALE_S = 180
#: «Нарушение сейчас» — окно последних секунд.
RECENT_S = 120


def _web_base_url() -> str | None:
    """Ссылка на UI в уведомлениях (env WEB_BASE_URL, опционально)."""
    return os.environ.get("WEB_BASE_URL") or None


def _ts_utc(now: int) -> str:
    """чч:мм:сс UTC из epoch."""
    return time.strftime("%H:%M:%S", time.gmtime(now))


def trigger_message(rule: Rule, now: int, detail: str) -> str:
    """Telegram-сообщение trigger: уровень, правило, detail, время, ссылка."""
    emoji = "🚨" if rule.level == "critical" else "⚠️"
    lines = [f"{emoji} [{rule.level.upper()}] llm-metrics", rule.title]
    if detail:
        lines.append(detail)
    lines.append(f"Время: {_ts_utc(now)} UTC")
    base = _web_base_url()
    if base:
        lines.append(f"{base}/alerts")
    return "\n".join(lines)


def resolve_message(rule: Rule, now: int) -> str:
    """Telegram-сообщение восстановления: название правила (title), время, ссылка."""
    lines = [f"✅ llm-metrics: «{rule.title}» — восстановлено", f"Время: {_ts_utc(now)} UTC"]
    base = _web_base_url()
    if base:
        lines.append(f"{base}/alerts")
    return "\n".join(lines)


class AlertEngine:
    def __init__(
        self,
        db,
        statuses: SourceRegistry,
        http: httpx.AsyncClient,
        *,
        default_enabled: bool,
        default_webhook: str | None,
        check_interval_s: int,
    ) -> None:
        self.db = db
        self.statuses = statuses
        self.http = http
        self.default_enabled = default_enabled
        self.default_webhook = default_webhook
        self.check_interval_s = check_interval_s
        # rule_id -> {"active": bool, "triggered_at": int, "resolved_at": int | None}
        self._states: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- state
    async def restore(self) -> None:
        """Восстановить активные алерты из журнала (после рестарта)."""
        rows = await self.db.execute_fetchall(
            "SELECT rule, level, message, triggered_at FROM alerts WHERE status = 'active'"
        )
        for r in rows:
            self._states[r["rule"]] = {
                "active": True,
                "triggered_at": r["triggered_at"],
                "resolved_at": None,
            }
        if self._states:
            log.info("alerts: восстановлено активных: %s", sorted(self._states))

    def active(self) -> list[dict[str, Any]]:
        rows = []
        for rule_id, st in self._states.items():
            if st.get("active"):
                rows.append({"rule": rule_id, "triggered_at": st["triggered_at"]})
        rows.sort(key=lambda r: r["triggered_at"], reverse=True)
        return rows

    def active_count(self) -> int:
        return sum(1 for st in self._states.values() if st.get("active"))

    # ------------------------------------------------------------- loop
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await wait_cancelable(stop, self.check_interval_s)
            if stop.is_set():
                break
            try:
                await self.check_once()
            except Exception:  # noqa: BLE001
                log.exception("alerts check failed")

    # ---------------------------------------------------------- checking
    async def check_once(self) -> None:
        stored = await get_alert_cfg(self.db)
        cfg = effective_cfg(
            stored,
            default_enabled=self.default_enabled,
            default_webhook=self.default_webhook,
        )
        if not cfg["enabled"]:
            # выключили — разводим активные без уведомлений
            await self._resolve_all(cfg["telegram_webhook"], silent=True, rules=cfg["rules"])
            return
        now = int(time.time())
        for rule in cfg["rules"]:
            try:
                cond, detail = await self._condition(rule, now)
            except Exception:  # noqa: BLE001
                log.exception("alert rule %s failed", rule.id)
                continue
            st = self._states.get(rule.id)
            active = bool(st and st.get("active"))
            webhook = rule.webhook or cfg["telegram_webhook"]
            if cond and not active:
                if not rule.enabled:
                    continue
                if self._in_cooldown(st, now, rule):
                    continue
                await self._trigger(rule, webhook, now, detail)
            elif not cond and active:
                await self._resolve(rule, webhook, now)

    async def _resolve_all(
        self, webhook: str | None, *, silent: bool, rules: list[Rule]
    ) -> None:
        by_id = {r.id: r for r in rules}
        active_rules = [k for k, st in self._states.items() if st.get("active")]
        for rule_id in active_rules:
            if silent:
                # Глобально выключили: закрываем и в БД (иначе restore их
                # «оживит» после рестарта), без уведомлений.
                now = int(time.time())
                await self.db.execute(
                    "UPDATE alerts SET status = 'resolved', resolved_at = ? "
                    "WHERE rule = ? AND status = 'active'",
                    (now, rule_id),
                )
                await self.db.commit()
                prev = self._states.get(rule_id) or {}
                self._states[rule_id] = {
                    "active": False,
                    "triggered_at": prev.get("triggered_at"),
                    "resolved_at": now,
                }
            else:
                rule = by_id.get(rule_id)
                if rule is not None:
                    await self._resolve(rule, rule.webhook or webhook, int(time.time()))
                else:
                    # правило удалено из конфига — закрыть в БД без уведомления
                    now = int(time.time())
                    await self.db.execute(
                        "UPDATE alerts SET status = 'resolved', resolved_at = ? "
                        "WHERE rule = ? AND status = 'active'",
                        (now, rule_id),
                    )
                    await self.db.commit()
                    prev = self._states.get(rule_id) or {}
                    self._states[rule_id] = {
                        "active": False,
                        "triggered_at": prev.get("triggered_at"),
                        "resolved_at": now,
                    }

    async def _trigger(self, rule: Rule, webhook: str | None, now: int, detail: str) -> None:
        await self.db.execute(
            "INSERT INTO alerts (rule, level, status, message, triggered_at) VALUES (?, ?, 'active', ?, ?)",
            (rule.id, rule.level, f"{rule.title}: {detail}" if detail else rule.title, now),
        )
        await self.db.commit()
        self._states[rule.id] = {"active": True, "triggered_at": now, "resolved_at": None}
        log.warning("ALERT [%s] %s: %s", rule.level, rule.title, detail)
        await self.notify(webhook, trigger_message(rule, now, detail))

    async def _resolve(self, rule: Rule, webhook: str | None, now: int) -> None:
        await self.db.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = ? "
            "WHERE rule = ? AND status = 'active'",
            (now, rule.id),
        )
        await self.db.commit()
        st = self._states.get(rule.id)
        self._states[rule.id] = {
            "active": False,
            "triggered_at": st["triggered_at"] if st else None,
            "resolved_at": now,
        }
        log.info("ALERT resolved: %s", rule.id)
        await self.notify(webhook, resolve_message(rule, now))

    def _in_cooldown(self, st: dict[str, Any] | None, now: int, rule: Rule) -> bool:
        if not st or st.get("resolved_at") is None:
            return False
        return now - st["resolved_at"] < rule.cooldown_s

    # -------------------------------------------------------- conditions
    async def _condition(self, rule: Rule, now: int) -> tuple[bool, str]:
        if rule.source:
            return self._source_condition(rule, now)
        if not rule.metric or rule.op is None or rule.value is None:
            return False, ""
        window = max(rule.for_s, RECENT_S)
        # Пер-GPU метрики (gpu_throttle_reasons и т.п.): худшее значение на
        # timestamp (MAX для ">", MIN для "<" — «нарушение на любой GPU»). Без
        # сводки устойчивое нарушение на 1 из N GPU = 1/N точек окна и никогда
        # не дотягивает до порога ≥50% (не-GPU-метрики: 1 строка на ts — сводка
        # не меняет значения).
        agg = "MAX(value)" if rule.op == ">" else "MIN(value)"
        rows = await self.db.execute_fetchall(
            f"SELECT ts, {agg} AS value FROM metric_samples "
            "WHERE metric = ? AND ts >= ? AND ts <= ? GROUP BY ts ORDER BY ts",
            (rule.metric, now - window, now),
        )
        if not rows:
            return False, ""
        last_ts, last_val = rows[-1]["ts"], rows[-1]["value"]
        if last_ts < now - STALE_S:
            return False, ""
        cmp = (lambda v: v > rule.value) if rule.op == ">" else (lambda v: v < rule.value)
        if not cmp(last_val):
            return False, ""
        # issue #6: «длится for_s» — устойчивое нарушение, а не единичный
        # всплеск: ≥50% точек окна for_s + свежая точка в последних 120 с
        window_violation = sum(cmp(r["value"]) for r in rows) >= len(rows) / 2
        recent_violation = any(cmp(r["value"]) for r in rows if r["ts"] >= now - RECENT_S)
        return (
            recent_violation and window_violation,
            f"{rule.metric}={last_val:g} (порог {rule.value:g})",
        )

    def _source_condition(self, rule: Rule, now: int) -> tuple[bool, str]:
        st = self.statuses[rule.source]
        if st.status != "offline":
            return False, ""
        # задержим for_s: краткий сбой не алертит
        if st.last_ok_ts is not None and now - st.last_ok_ts < rule.for_s:
            return False, ""
        err = (st.last_error or "")[:120]
        return True, err or "источник недоступен"

    # ----------------------------------------------------------- telegram
    async def notify(self, webhook: str | None, text: str) -> bool:
        """Отправка в Telegram (best effort). True — отправлено."""
        if not webhook:
            return False
        try:
            resp = await self.http.post(
                webhook, json={"text": text}, timeout=httpx.Timeout(10.0)
            )
            if resp.status_code >= 300:
                log.warning("telegram webhook %s: HTTP %s", webhook[:60], resp.status_code)
                return False
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("telegram webhook send failed: %s", e)
            return False

    async def send_test(self, webhook: str | None) -> tuple[bool, str]:
        ok = await self.notify(
            webhook, "✅ llm-metrics: тестовое уведомление алертов"
        )
        if ok:
            return True, "Отправлено"
        if not webhook:
            return False, "Webhook не задан"
        return False, "Не удалось отправить (проверьте URL)"
