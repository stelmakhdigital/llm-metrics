"""Log-tailer (F3): file tail по offset+inode, ротация, удаление, ретенция.

Дocker-ветка здесь не проверяется (нет docker в dev-окружении) — покрывается
логикой статусов offline/last_error в коде и инструкцией в README.
"""

import os
import time

import pytest

from app.collectors.base import SourceRegistry
from app.config import LogSource, LogSources
from app.logs.tailer import LogLineBuffer, LogTailer, purge_old_logs


@pytest.fixture
def env(tmp_path, db):
    logfile = tmp_path / "t.log"
    logfile.write_text("first line (before start)\n")
    cfg = LogSources(
        sources=[LogSource(name="t", type="file", path=str(logfile))],
        poll_seconds=0.2,
        retention_days=14,
    )
    statuses = SourceRegistry(("logs.t",))
    buffer = LogLineBuffer()
    tailer = LogTailer(cfg, db, statuses, buffer)
    return {"tailer": tailer, "file": logfile, "statuses": statuses, "buffer": buffer}


async def _rows(db):
    return await db.execute_fetchall("SELECT ts, level, source, line FROM log_entries")


async def test_tail_append_rotate_delete(env):
    tailer, f, statuses, buffer = (
        env["tailer"], env["file"], env["statuses"], env["buffer"]
    )

    # первая встреча файла — старт с конца: старая строка не индексируется
    await tailer.poll_once()
    assert statuses["logs.t"].status == "online"
    assert len(await _rows(tailer.db)) == 0

    with f.open("a") as fh:
        fh.write("2026-07-25 12:00:00,123 [INFO] uvicorn hello\n")
        fh.write(
            "INFO 07-10 12:00:00 [vllm] Engine00: Running: 3 reqs, "
            "Waiting: 2 reqs, GPU KV cache usage: 12.3%, "
            "Prefix cache hit rate: 4.5%\n"
        )
        fh.write("WARN: disk almost full\n")
        fh.write("plain stdout garbage\n")
    await tailer.poll_once()
    await tailer.flush(force=True)

    db = tailer.db
    rows = await db.execute_fetchall(
        "SELECT ts, level, source, line FROM log_entries ORDER BY id"
    )
    assert len(rows) == 4
    assert rows[0]["level"] == "INFO" and "uvicorn hello" in rows[0]["line"]
    assert rows[1]["level"] == "INFO" and "Running: 3 reqs" in rows[1]["line"]
    assert rows[2]["level"] == "WARNING"
    assert rows[3]["level"] == "INFO"  # мусор без уровня → INFO
    assert all(r["source"] == "t" for r in rows)
    # буфер для SSE: id заполнены, порядок сохраняется
    assert len(buffer) == 4
    assert [e["id"] for e in buffer.all()] == [1, 2, 3, 4]

    # повторный poll без новых строк — ничего не дублируется
    await tailer.poll_once()
    await tailer.flush(force=True)
    assert len(await _rows(db)) == 4

    # ротация: файл переименован, создан новый — читаем новый с начала
    rotated = f.with_suffix(".1")
    os.replace(f, rotated)
    f.write_text("2026-07-25 13:00:00,000 [ERROR] new file after rotate\n")
    await tailer.poll_once()
    await tailer.flush(force=True)
    rows = await db.execute_fetchall(
        "SELECT level, line FROM log_entries ORDER BY id DESC LIMIT 1"
    )
    assert rows[0]["level"] == "ERROR" and "after rotate" in rows[0]["line"]
    assert len(await _rows(db)) == 5

    # удаление файла — источник offline, приложение живёт
    os.remove(f)
    await tailer.poll_once()
    st = statuses["logs.t"]
    assert st.status == "offline"
    assert "файл отсутствует" in st.last_error


async def test_retention_purge(db, db_path):
    from conftest import seed_log_entries

    now_ms = time.time() * 1000
    seed_log_entries(
        db_path,
        [
            (int(now_ms - 15 * 86400 * 1000), "INFO", "old 1", "t"),
            (int(now_ms - 20 * 86400 * 1000), "ERROR", "old 2", "t"),
            (int(now_ms - 3 * 86400 * 1000), "INFO", "new 1", "t"),
            (int(now_ms), "INFO", "new 2", "t"),
        ],
    )
    deleted = await purge_old_logs(db, 14)
    assert deleted == 2
    rows = await db.execute_fetchall("SELECT line FROM log_entries ORDER BY line")
    assert [r["line"] for r in rows] == ["new 1", "new 2"]

    # батчи: больше одной пачки
    seed_log_entries(
        db_path,
        [
            (int(now_ms - 15 * 86400 * 1000 + i), "INFO", f"batch {i}", "t")
            for i in range(6000)
        ],
    )
    deleted = await purge_old_logs(db, 14, batch=5000)
    assert deleted == 6000
    rows = await db.execute_fetchall("SELECT line FROM log_entries")
    assert len(rows) == 2
