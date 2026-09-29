"""Тесты агрегатора: hourly/daily + токены-дельты (async, temp БД)."""

import time

import pytest

from app.aggregator import Aggregator, p95_of_sorted
from app.config import Retention
from conftest import seed_samples_aio

NOW = int(time.time())
HOUR = (NOW // 3600 - 2) * 3600  # закрытый час (2 назад)
DAY = (NOW // 86400 - 1) * 86400  # закрытые сутки (вчера)


@pytest.fixture
async def agg(db):
    return Aggregator(db, Retention(raw_hours=168, hourly_days=180, daily_days=None))


async def test_hourly_stats(agg, db):
    rows = [
        ("cpu_usage", HOUR + i, float(i), "system", None, None)
        for i in range(100)
    ]
    await seed_samples_aio(db, rows)
    stats = await agg._aggregate_hourly(NOW)
    assert stats == 1
    r = (await db.execute_fetchall(
        "SELECT * FROM metric_hourly WHERE metric='cpu_usage' AND hour=?", (HOUR,)
    ))[0]
    d = dict(r)
    assert d["count"] == 100
    assert d["min"] == 0.0
    assert d["max"] == 99.0
    assert d["avg"] == pytest.approx(49.5)
    # p95: индекс 0.95*99 = 94.05 → 94*0.95 + 95*0.05 ≈ 94.05
    assert d["p95"] == pytest.approx(p95_of_sorted(list(range(100))))


async def test_hourly_idempotent(agg, db):
    await seed_samples_aio(db, [("m", HOUR + 10, 5.0, "vllm", None, "x")])
    await agg._aggregate_hourly(NOW)
    await agg._aggregate_hourly(NOW)
    n = (await db.execute_fetchall(
        "SELECT count(*) c FROM metric_hourly WHERE metric='m'"
    ))[0]["c"]
    assert n == 1


async def test_hourly_skips_open_window(agg, db):
    # Выборки только в НЕзакрытом (текущем) часу — ничего не пишем
    await seed_samples_aio(db, [("m", NOW, 5.0, "vllm", None, "x")])
    assert await agg._aggregate_hourly(NOW) == 0
    assert len(await db.execute_fetchall("SELECT * FROM metric_hourly")) == 0


async def test_hourly_multigpu(agg, db):
    # gpu-метрики — отдельная строка на (metric, hour, gpu); остальные — gpu=NULL
    rows = []
    for i in range(10):
        rows.append(("gpu_power", HOUR + i * 60, 300.0, "gpu", 0, None))
        rows.append(("gpu_power", HOUR + i * 60, 500.0, "gpu", 1, None))
        rows.append(("cpu_usage", HOUR + i * 60, 10.0, "system", None, None))
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_hourly(NOW) == 3  # gpu_power×2 gpu + cpu_usage
    got = {
        (dict(r)["metric"], dict(r)["gpu"]): dict(r)
        for r in await db.execute_fetchall(
            "SELECT * FROM metric_hourly WHERE hour=?", (HOUR,)
        )
    }
    assert set(got) == {("gpu_power", 0), ("gpu_power", 1), ("cpu_usage", None)}
    assert got[("gpu_power", 0)]["avg"] == pytest.approx(300.0)
    assert got[("gpu_power", 0)]["count"] == 10
    assert got[("gpu_power", 1)]["avg"] == pytest.approx(500.0)
    assert got[("cpu_usage", None)]["avg"] == pytest.approx(10.0)


async def test_daily_multigpu(agg, db):
    # daily — раздельно по gpu: avg по hourly per-gpu
    rows = []
    for h in range(8):
        rows.append(("gpu_power", DAY + h * 3600 + 1800, 300.0, "gpu", 0, None))
        rows.append(("gpu_power", DAY + h * 3600 + 1800, 500.0, "gpu", 1, None))
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_hourly(NOW) == 16  # 8 часов × 2 gpu
    assert await agg._aggregate_daily(NOW) == 2
    got = {
        dict(r)["gpu"]: dict(r)
        for r in await db.execute_fetchall(
            "SELECT * FROM metric_daily WHERE metric='gpu_power'"
        )
    }
    assert got[0]["avg"] == pytest.approx(300.0)
    assert got[1]["avg"] == pytest.approx(500.0)
    assert got[0]["sum"] == pytest.approx(2400.0)
    assert got[0]["count"] == 8


async def test_daily_from_hourly(agg, db):
    rows = []
    for h in range(8):  # 8 часов (>= MIN_HOURLY_PER_DAY)
        rows.append(("m", DAY + h * 3600 + 1800, 10.0 + h, "system", None, None))
    await seed_samples_aio(db, rows)
    await agg._aggregate_hourly(NOW)
    await agg._aggregate_daily(NOW)
    rs = await db.execute_fetchall("SELECT * FROM metric_daily WHERE metric='m'")
    assert len(rs) == 1
    d = dict(rs[0])
    assert d["count"] == 8
    assert d["min"] == pytest.approx(10.0)
    assert d["max"] == pytest.approx(17.0)
    assert d["avg"] == pytest.approx(13.5)
    assert d["sum"] == pytest.approx(108.0)


async def test_daily_skipped_when_sparse(agg, db):
    for h in range(2):
        await seed_samples_aio(db, [("m", DAY + h * 3600 + 1800, 1.0, "system", None, None)])
    await agg._aggregate_hourly(NOW)
    await agg._aggregate_daily(NOW)
    assert len(await db.execute_fetchall("SELECT * FROM metric_daily")) == 0


async def test_tokens_deltas(agg, db):
    # Базовые замеры до окна и внутри окна
    rows = [
        ("prompt_tokens_total", HOUR - 300, 1000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR - 300, 500.0, "vllm", None, "m"),
        ("request_success_total_stop", HOUR - 300, 10.0, "vllm", None, "m"),
        ("request_success_total_length", HOUR - 300, 1.0, "vllm", None, "m"),
        ("prompt_tokens_total", HOUR + 1800, 3000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR + 1800, 900.0, "vllm", None, "m"),
        ("request_success_total_stop", HOUR + 1800, 25.0, "vllm", None, "m"),
        ("request_success_total_length", HOUR + 1800, 2.0, "vllm", None, "m"),
    ]
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_tokens(NOW) == 1
    r = dict((await db.execute_fetchall("SELECT * FROM tokens WHERE ts=?", (HOUR,)))[0])
    assert r["prompt_tokens"] == 2000
    assert r["completion_tokens"] == 400
    assert r["requests_finished"] == 16  # (25-10) + (2-1)


async def test_tokens_skips_restart(agg, db):
    rows = [
        ("prompt_tokens_total", HOUR - 300, 1000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR - 300, 500.0, "vllm", None, "m"),
        # В окне prompt «упал» → недостоверно → строка не пишется
        ("prompt_tokens_total", HOUR + 1800, 10.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR + 1800, 900.0, "vllm", None, "m"),
    ]
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_tokens(NOW) == 0
    assert len(await db.execute_fetchall("SELECT * FROM tokens")) == 0


async def test_tokens_skips_stale_baseline(agg, db):
    rows = [
        ("prompt_tokens_total", HOUR - 9999, 1000.0, "vllm", None, "m"),  # > 2ч разрыв
        ("generation_tokens_total", HOUR - 9999, 500.0, "vllm", None, "m"),
        ("prompt_tokens_total", HOUR + 1800, 3000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR + 1800, 900.0, "vllm", None, "m"),
    ]
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_tokens(NOW) == 0


async def test_tokens_idempotent(agg, db):
    rows = [
        ("prompt_tokens_total", HOUR - 300, 1000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR - 300, 500.0, "vllm", None, "m"),
        ("prompt_tokens_total", HOUR + 1800, 3000.0, "vllm", None, "m"),
        ("generation_tokens_total", HOUR + 1800, 900.0, "vllm", None, "m"),
    ]
    await seed_samples_aio(db, rows)
    await agg._aggregate_tokens(NOW)
    assert await agg._aggregate_tokens(NOW) == 0
    assert len(await db.execute_fetchall("SELECT * FROM tokens")) == 1


async def test_hourly_per_model(agg, db):
    # vllm-метрики — отдельная строка на (metric, hour, model); смена модели
    # внутри часа — две строки (F4.4 без 168ч-лимита)
    rows = []
    for i in range(10):
        rows.append(("ttft_p50", HOUR + i * 60, 1.0 + i, "vllm", None, "model-a"))
        rows.append(("ttft_p50", HOUR + 1800 + i * 60, 5.0, "vllm", None, "model-b"))
        rows.append(("cpu_usage", HOUR + i * 60, 10.0, "system", None, None))
    await seed_samples_aio(db, rows)
    assert await agg._aggregate_hourly(NOW) == 3  # ttft×2 модели + cpu
    got = {
        dict(r)["model"]: dict(r)
        for r in await db.execute_fetchall(
            "SELECT * FROM metric_hourly WHERE hour=? AND metric='ttft_p50'", (HOUR,)
        )
    }
    assert set(got) == {"model-a", "model-b"}
    assert got["model-a"]["count"] == 10
    assert got["model-b"]["count"] == 10
    # cpu (model=NULL) — одна строка
    cpu = (await db.execute_fetchall(
        "SELECT count(*) c FROM metric_hourly WHERE metric='cpu_usage' AND model IS NULL"
    ))[0]["c"]
    assert cpu == 1
