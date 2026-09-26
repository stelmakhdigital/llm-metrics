"""Тесты ретенции (raw 168ч / hourly 180д / daily null — безлимит)."""

import time

import pytest

from app.aggregator import Aggregator
from app.config import Retention

NOW = int(time.time())
RAW_CUTOFF = NOW - 168 * 3600
HOURLY_CUTOFF = NOW - 180 * 86400


@pytest.fixture
async def agg(db):
    return Aggregator(db, Retention(raw_hours=168, hourly_days=180, daily_days=None))


async def test_raw_retention(agg, db):
    rows = [
        ("old", RAW_CUTOFF - 10, 1.0, "system"),
        ("old", RAW_CUTOFF - 1, 1.0, "system"),
        ("new", NOW - 100, 1.0, "system"),
    ]
    await db.executemany(
        "INSERT INTO metric_samples (metric, ts, value, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    await db.commit()
    deleted = await agg._apply_retention(NOW)
    assert deleted == 2
    left = await db.execute_fetchall("SELECT metric FROM metric_samples")
    assert [r["metric"] for r in left] == ["new"]


async def test_hourly_and_daily_retention(agg, db):
    await db.execute(
        "INSERT INTO metric_hourly (metric, hour, avg) VALUES ('m', ?, 1.0), ('m', ?, 1.0)",
        (HOURLY_CUTOFF - 10, NOW - 3600),
    )
    await db.execute(
        "INSERT INTO metric_daily (metric, day, avg) VALUES ('m', ?, 1.0)",
        (NOW - 999 * 86400,),
    )
    await db.commit()
    await agg._apply_retention(NOW)
    # hourly: старый удалён, новый остался
    hours = await db.execute_fetchall("SELECT hour FROM metric_hourly")
    assert [h["hour"] for h in hours] == [NOW - 3600]
    # daily: retention=null → безлимитно, строка осталась
    assert len(await db.execute_fetchall("SELECT * FROM metric_daily")) == 1


async def test_daily_retention_when_configured(db):
    agg = Aggregator(db, Retention(raw_hours=168, hourly_days=180, daily_days=365))
    await db.execute(
        "INSERT INTO metric_daily (metric, day, avg) VALUES ('m', ?, 1.0), ('m', ?, 1.0)",
        (NOW - 500 * 86400, NOW - 3600),
    )
    await db.commit()
    await agg._apply_retention(NOW)
    days = await db.execute_fetchall("SELECT day FROM metric_daily")
    assert [d["day"] for d in days] == [NOW - 3600]


async def test_batched_delete(agg, db):
    # 2500 старых строк, батч 1000 → 3 итерации
    rows = [("m", RAW_CUTOFF - i, 1.0, "system") for i in range(2500)]
    await db.executemany(
        "INSERT INTO metric_samples (metric, ts, value, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    await db.commit()
    deleted = await agg._delete_old("metric_samples", "ts", NOW, batch=1000)
    assert deleted == 2500
    assert len(await db.execute_fetchall("SELECT * FROM metric_samples")) == 0


async def test_noop_when_fresh(agg, db):
    assert await agg._apply_retention(NOW) == 0
