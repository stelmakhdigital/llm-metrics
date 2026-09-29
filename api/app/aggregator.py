"""Фоновый агрегатор: hourly/daily + токены-дельты + ретенция (ТЗ §4, §5.3).

Запускается раз в 5 минут («catch-up» цикл):
* для каждого закрытого часового окна, в котором есть сырые выборки и ещё нет
  строки в ``metric_hourly`` — avg/min/max/p95/count (p95 — линейная
  интерполяция по сортированным точкам окна); gpu-метрики (``gpu IS NOT NULL``
  в raw) — отдельная строка на (metric, hour, gpu), остальные — gpu=NULL;
* для закрытых суток без строки в ``metric_daily`` — сводка из
  ``metric_hourly`` (min = min(min), max = max(max), avg/p95/sum — средневзвешенные
  по count; день пишется, когда в окне не меньше ``min_hourly`` часов),
  так же раздельно по gpu;
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
from collections import defaultdict

from .config import Retention
from .model_counters import hour_model_row
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
            "model_tokens": await self._aggregate_model_tokens(now),
            "deleted": await self._apply_retention(now),
        }
        log.info("aggregator cycle: %s", stats)
        return stats

    # --------------------------------------------------------------- hourly
    async def _aggregate_hourly(self, now: int) -> int:
        """Закрывающиеся часы: newest-first, не более MAX_HOURS_PER_CYCLE.

        Выборки группируются по (metric, gpu, model): gpu-метрики получают
        отдельную строку на gpu, vllm-метрики — отдельную на model
        (смена модели внутри часа — две строки)."""
        last_closed_hour = (now // 3600) * 3600  # окно [H, H+3600) с H < now
        horizon = last_closed_hour - MAX_HOURS_PER_CYCLE * 3600
        written = 0
        for hour in range(last_closed_hour - 3600, horizon - 3600, -3600):
            rows = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT metric, COALESCE(gpu, -1) AS g, COALESCE(model, '') AS m,
                              value
                       FROM metric_samples WHERE ts >= ? AND ts < ?""",
                    (hour, hour + 3600),
                )
            )
            if not rows:
                continue
            groups: dict[tuple[str, int, str], list[float]] = defaultdict(list)
            for r in rows:
                groups[(r["metric"], r["g"], r["m"])].append(r["value"])
            for (metric, g, m), values in groups.items():
                gpu = None if g == -1 else g
                model = m or None
                if await self._hourly_exists(metric, hour, gpu, model):
                    continue
                values.sort()
                n = len(values)
                await self.conn.execute(
                    """INSERT INTO metric_hourly
                         (metric, hour, gpu, model, avg, min, max, p95, count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        metric,
                        hour,
                        gpu,
                        model,
                        sum(values) / n,
                        values[0],
                        values[-1],
                        p95_of_sorted(values),
                        n,
                    ),
                )
                written += 1
        await self.conn.commit()
        return written

    @staticmethod
    def _gpu_cond(gpu: int | None) -> tuple[str, tuple]:
        """SQL-фрагмент условия по gpu (NULL-safe)."""
        if gpu is None:
            return " AND gpu IS NULL", ()
        return " AND gpu = ?", (gpu,)

    @staticmethod
    def _model_cond(model: str | None) -> tuple[str, tuple]:
        """SQL-фрагмент условия по model (NULL-safe)."""
        if model is None:
            return " AND model IS NULL", ()
        return " AND model = ?", (model,)

    async def _hourly_exists(
        self, metric: str, hour: int, gpu: int | None, model: str | None = None
    ) -> bool:
        gcond, gparams = self._gpu_cond(gpu)
        mcond, mparams = self._model_cond(model)
        cur = await self.conn.execute_fetchall(
            f"SELECT 1 FROM metric_hourly WHERE metric = ? AND hour = ?{gcond}{mcond}",
            (metric, hour, *gparams, *mparams),
        )
        return len(cur) > 0

    # --------------------------------------------------------------- daily
    async def _aggregate_daily(self, now: int) -> int:
        """Сутки из hourly (только закрытые; горизонт — ретенция hourly).

        Сводка — раздельно по (metric, gpu, model): gpu-метрики — отдельная
        суточная строка на gpu, vllm-метрики — на model (avg по hourly,
        взвешенно по count)."""
        last_closed_day = (now // 86400) * 86400
        horizon = last_closed_day - (self.ret.hourly_days + 1) * 86400
        written = 0
        for day in range(last_closed_day - 86400, horizon - 86400, -86400):
            metrics = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT metric, COALESCE(gpu, -1) AS g, COALESCE(model, '') AS m,
                              count(*) AS n
                       FROM metric_hourly
                       WHERE hour >= ? AND hour < ?
                       GROUP BY metric, COALESCE(gpu, -1), COALESCE(model, '')""",
                    (day, day + 86400),
                )
            )
            for row in metrics:
                if row["n"] < MIN_HOURLY_PER_DAY:
                    continue  # не хватит данных — дождёмся
                gpu = None if row["g"] == -1 else row["g"]
                model = row["m"] or None
                gcond, gparams = self._gpu_cond(gpu)
                mcond, mparams = self._model_cond(model)
                cur = await self.conn.execute_fetchall(
                    f"SELECT 1 FROM metric_daily WHERE metric = ? AND day = ?{gcond}{mcond}",
                    (row["metric"], day, *gparams, *mparams),
                )
                if cur:
                    continue
                s = rows_to_dicts(
                    await self.conn.execute_fetchall(
                        f"""SELECT avg(avg) AS av, min(min) AS mn, max(max) AS mx,
                                   avg(p95) AS p95, sum(avg * count) AS sm, sum(count) AS ct
                           FROM metric_hourly WHERE metric = ? AND hour >= ? AND hour < ?{gcond}{mcond}""",
                        (row["metric"], day, day + 86400, *gparams, *mparams),
                    )
                )[0]
                if not s["ct"]:
                    continue
                await self.conn.execute(
                    """INSERT INTO metric_daily
                         (metric, day, gpu, model, avg, min, max, p95, sum, count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["metric"], day, gpu, model, s["av"], s["mn"], s["mx"],
                     s["p95"], s["sm"], s["ct"]),
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

    async def _aggregate_model_tokens(self, now: int) -> int:
        """Дельты счётчиков vLLM по модели на закрытый час (issue #5).

        Только для часов, где ещё есть raw (ретенция raw_hours; горизонт
        за цикл — MAX_HOURS_PER_CYCLE, старейшие догоняются)."""
        last_closed_hour = (now // 3600) * 3600
        horizon = max(
            last_closed_hour - MAX_HOURS_PER_CYCLE * 3600,
            now - self.ret.raw_hours * 3600,
        )
        written = 0
        for hour in range(last_closed_hour - 3600, horizon - 3600, -3600):
            models = rows_to_dicts(
                await self.conn.execute_fetchall(
                    """SELECT DISTINCT model FROM metric_samples
                       WHERE source = 'vllm' AND model IS NOT NULL
                         AND ts >= ? AND ts < ?""",
                    (hour, hour + 3600),
                )
            )
            for r in models:
                model = r["model"]
                if not model:
                    continue
                exists = await self.conn.execute_fetchall(
                    "SELECT 1 FROM model_tokens WHERE ts = ? AND model = ?",
                    (hour, model),
                )
                if exists:
                    continue
                row = await hour_model_row(self.conn, hour, model)
                if row is None:
                    continue
                await self.conn.execute(
                    """INSERT OR IGNORE INTO model_tokens
                       (ts, model, prompt_tokens, completion_tokens,
                        requests_finished, finish_reasons, preemptions,
                        prefix_hits, prefix_queries, prompt_dist,
                        generation_dist)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        hour, model, row["prompt_tokens"], row["completion_tokens"],
                        row["requests_finished"], row["finish_reasons"],
                        row["preemptions"], row["prefix_hits"], row["prefix_queries"],
                        row["prompt_dist"], row["generation_dist"],
                    ),
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
