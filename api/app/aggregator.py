"""Фоновый агрегатор: hourly/daily + токены-дельты + ретенция (ТЗ §4, §5.3).

Запускается раз в 5 минут («catch-up» цикл):
* для каждого закрытого часового окна, в котором есть сырые выборки и ещё нет
  строки в ``metric_hourly`` — avg/min/max/p95/count (p95 — линейная
  интерполяция по сортированным точкам окна);
* для закрытых суток без строки в ``metric_daily`` — сводка из
  ``metric_hourly`` (min = min(min), max = max(max), avg/p95/sum — средневзвешенные
  по count; день пишется, когда в окне не меньше ``min_hourly`` часов);
* для закрытых часов без строки в ``tokens`` — дельты сырых счётчиков
  vLLM (prompt/completion токены, завершённые запросы по finish reasons)
  между последним значением до окна и последним внутри окна;
* ретенция: сырые ``raw_hours``, hourly ``hourly_days``, daily ``daily_days``
  (None — безлимитно). Удаление пачками (``BATCH``), чтобы не держать БД
  заблокированной.
"""

from __future__ import annotations

import logging
import math
import time

from .config import Retention
from .storage.db import rows_to_dicts

log = logging.getLogger(__name__)

__all__ = ["Aggregator", "HOURLY_RAW_COUNTERS", "FINISH_REASON_PREFIX"]

HOURLY_RAW_COUNTERS = ("prompt_tokens_total", "generation_tokens_total")
FINISH_REASON_PREFIX = "request_success_total_"

# Часовых окон, обрабатываемых за один цикл (ограничение рабочей загрузки;
# старейшие догоняются последующими циклами)
MAX_HOURS_PER_CYCLE = 96
# Минимум часовых строк для записи суточной
MIN_HOURLY_PER_DAY = 6
BATCH = 100_000


def p95_of_sorted(values: list[float]) -> float:
    """p95 для отсортированных значений (линейная интерполяция)."""
    n = len(values)
    if n == 0:
        raise ValueError("no values")
    if n == 1:
        return values[0]
    idx = 0.95 * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return values[lo]
    frac = idx - lo
    return values[lo] * (1 - frac) + values[hi] * frac


class Aggregator:
    def __init__(self, conn, retention: Retention):
        self.conn = conn
        self.ret = retention

    # ------------------------------------------------------------------ run
    async def run_cycle(self) -> dict[str, int]:
        """Один catch-up цикл. Возвращает счётчики для логирования."""
        now = int(time.time())
        stats = {
            "hours": await self._aggregate_hourly(now),
            "days": await self._aggregate_daily(now),
            "tokens": await self._aggregate_tokens(now),
            "deleted": await self._apply_retention(now),
        }
        log.info("aggregator cycle: %s", stats)
        return stats

    # --------------------------------------------------------------- hourly
    async def _aggregate_hourly(self, now: int) -> int:
        """Закрывающиеся часы: newest-first, не более MAX_HOURS_PER_CYCLE."""
        last_closed_hour = (now // 3600) * 3600  # окно [H, H+3600) с H < now
        horizon = last_closed_hour - MAX_HOURS_PER_CYCLE * 3600
        written = 0
        for hour in range(last_closed_hour - 3600, horizon - 3600, -3600):
            metrics = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT DISTINCT metric FROM metric_samples
                       WHERE ts >= ? AND ts < ?""",
                    (hour, hour + 3600),
                )
            )
            if not metrics:
                continue
            for row in metrics:
                if await self._hourly_exists(row["metric"], hour):
                    continue
                stats = await self._hourly_stats(row["metric"], hour)
                if stats is None:
                    continue
                await self.conn.execute(
                    """INSERT INTO metric_hourly
                         (metric, hour, avg, min, max, p95, count)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["metric"],
                        hour,
                        stats["avg"],
                        stats["min"],
                        stats["max"],
                        stats["p95"],
                        stats["count"],
                    ),
                )
                written += 1
        await self.conn.commit()
        return written

    async def _hourly_exists(self, metric: str, hour: int) -> bool:
        cur = await self.conn.execute_fetchall(
            "SELECT 1 FROM metric_hourly WHERE metric = ? AND hour = ?",
            (metric, hour),
        )
        return len(cur) > 0

    async def _hourly_stats(self, metric: str, hour: int) -> dict[str, float] | None:
        cur = await self.conn.execute_fetchall(
            """SELECT count(*) AS n, min(value) AS mn, max(value) AS mx, avg(value) AS av
               FROM metric_samples WHERE metric = ? AND ts >= ? AND ts < ?""",
            (metric, hour, hour + 3600),
        )
        row = rows_to_dicts(cur)[0]
        n = row["n"]
        if n == 0:
            return None
        # p95 — по точкам окна (линейная интерполяция, метод ТЗ §5.2)
        vals = rows_to_dicts(
            await self.conn.execute_fetchall(
                "SELECT value FROM metric_samples WHERE metric = ? AND ts >= ? AND ts < ? ORDER BY value",
                (metric, hour, hour + 3600),
            )
        )
        values = [r["value"] for r in vals]
        return {
            "avg": row["av"],
            "min": row["mn"],
            "max": row["mx"],
            "p95": p95_of_sorted(values),
            "count": n,
        }

    # --------------------------------------------------------------- daily
    async def _aggregate_daily(self, now: int) -> int:
        """Сутки из hourly (только закрытые; горизонт — ретенция hourly)."""
        last_closed_day = (now // 86400) * 86400
        horizon = last_closed_day - (self.ret.hourly_days + 1) * 86400
        written = 0
        for day in range(last_closed_day - 86400, horizon - 86400, -86400):
            metrics = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT metric, count(*) AS n
                       FROM metric_hourly
                       WHERE hour >= ? AND hour < ?
                       GROUP BY metric""",
                    (day, day + 86400),
                )
            )
            for row in metrics:
                if row["n"] < MIN_HOURLY_PER_DAY:
                    continue  # не хватит данных — дождёмся
                cur = await self.conn.execute_fetchall(
                    "SELECT 1 FROM metric_daily WHERE metric = ? AND day = ?",
                    (row["metric"], day),
                )
                if cur:
                    continue
                s = rows_to_dicts(
                    await self.conn.execute_fetchall(
                        """SELECT avg(avg) AS av, min(min) AS mn, max(max) AS mx,
                                  avg(p95) AS p95, sum(avg * count) AS sm, sum(count) AS ct
                           FROM metric_hourly WHERE metric = ? AND hour >= ? AND hour < ?""",
                        (row["metric"], day, day + 86400),
                    )
                )[0]
                if not s["ct"]:
                    continue
                await self.conn.execute(
                    """INSERT INTO metric_daily
                         (metric, day, avg, min, max, p95, sum, count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["metric"], day, s["av"], s["mn"], s["mx"], s["p95"], s["sm"], s["ct"]),
                )
                written += 1
        await self.conn.commit()
        return written

    # --------------------------------------------------------------- tokens
    async def _aggregate_tokens(self, now: int) -> int:
        """Дельты счётчиков vLLM за каждый закрытый час (без строки в tokens)."""
        last_closed_hour = (now // 3600) * 3600
        horizon = last_closed_hour - MAX_HOURS_PER_CYCLE * 3600
        written = 0
        for hour in range(last_closed_hour - 3600, horizon - 3600, -3600):
            if await self._tokens_exists(hour):
                continue
            # Есть ли в окне vllm-счётчики вообще
            has = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT 1 FROM metric_samples
                       WHERE ts >= ? AND ts < ? AND metric = ? LIMIT 1""",
                    (hour, hour + 3600, "prompt_tokens_total"),
                )
            )
            if not has:
                continue
            prompt = await self._counter_delta("prompt_tokens_total", hour)
            completion = await self._counter_delta("generation_tokens_total", hour)
            if prompt is None or completion is None:
                continue  # разрыв — пропускаем, не пишем 0 (ТЗ §8.2)
            requests = 0
            finished = 0
            reasons = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT DISTINCT metric FROM metric_samples
                      WHERE metric LIKE ? AND ts >= ? AND ts < ?""",
                    (FINISH_REASON_PREFIX + "%", hour, hour + 3600),
                )
            )
            for r in reasons:
                d = await self._counter_delta(r["metric"], hour)
                if d is not None:
                    requests += d
                    finished = 1
            await self.conn.execute(
                """INSERT INTO tokens (ts, prompt_tokens, completion_tokens, requests_finished)
                   VALUES (?, ?, ?, ?)""",
                (hour, prompt, completion, requests if finished else None),
            )
            written += 1
        await self.conn.commit()
        return written

    async def _tokens_exists(self, hour: int) -> bool:
        cur = await self.conn.execute_fetchall(
            "SELECT 1 FROM tokens WHERE ts = ?", (hour,)
        )
        return len(cur) > 0

    async def _counter_delta(self, metric: str, hour: int) -> int | None:
        """Δ сырого счётчика за час: last(в окне) − last(до окна).

        None, если данные не найдены, разрыв > 1 часа до окна или счётчик
        уменьшился (рестарт процесса).
        """
        in_win = rows_to_dicts(
            await self.conn.execute_fetchall(
                """SELECT value, ts FROM metric_samples
                   WHERE metric = ? AND ts >= ? AND ts < ?
                   ORDER BY ts DESC LIMIT 1""",
                (metric, hour, hour + 3600),
            )
        )
        if not in_win:
            return None
        before = rows_to_dicts(
            await self.conn.execute_fetchall(
                """SELECT value, ts FROM metric_samples
                   WHERE metric = ? AND ts < ?
                   ORDER BY ts DESC LIMIT 1""",
                (metric, hour),
            )
        )
        if not before:
            return None
        prev_ts, prev_val = before[0]["ts"], before[0]["value"]
        if hour - prev_ts > 7200:
            return None  # старый базовый замер — разрыв
        delta = int(round(in_win[0]["value"] - prev_val))
        if delta < 0:
            return None  # рестарт vLLM — дельта недостоверна
        return delta

    # ------------------------------------------------------------ retention
    async def _apply_retention(self, now: int) -> int:
        """Удаление по ретенции, пачками по BATCH строк."""
        deleted = 0
        deleted += await self._delete_old(
            "metric_samples", "ts", now - self.ret.raw_hours * 3600
        )
        deleted += await self._delete_old(
            "metric_hourly", "hour", now - self.ret.hourly_days * 86400
        )
        deleted += await self._delete_old("tokens", "ts", now - self.ret.hourly_days * 86400)
        if self.ret.daily_days is not None:
            deleted += await self._delete_old(
                "metric_daily", "day", now - self.ret.daily_days * 86400
            )
        return deleted

    async def _delete_old(
        self, table: str, col: str, cutoff: int, batch: int = BATCH
    ) -> int:
        deleted = 0
        while True:
            cur = await self.conn.execute(
                f"""DELETE FROM {table}
                    WHERE rowid IN (
                        SELECT rowid FROM {table} WHERE {col} < ? LIMIT ?
                    )""",
                (cutoff, batch),
            )
            n = cur.rowcount or 0
            deleted += n
            if n < batch:
                break
        if deleted:
            await self.conn.commit()
            log.info("retention: %s.%s < %s — удалено %s", table, col, cutoff, deleted)
        return deleted
