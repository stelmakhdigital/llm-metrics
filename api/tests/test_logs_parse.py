"""Парсер уровней/таймстампов и stat-паттерны vLLM (F3).

Набор образцовых строк: vLLM (stat-строки, короткие даты), uvicorn, syslog,
epoch-форматы и stdout-мусор.
"""

from datetime import datetime, timedelta, timezone

from app.logs.parse import LEVELS, normalize_level, parse_level, parse_line, parse_ts_ms
from app.logs.patterns import parse_vllm_stat

NOW = datetime.now().astimezone()
LOCAL_TZ = NOW.tzinfo


def _local_ms(*args) -> int:
    return int(datetime(*args, tzinfo=LOCAL_TZ).timestamp() * 1000)


# ------------------------------------------------------------- таймстампы

def test_ts_iso_z():
    v = parse_ts_ms("2026-07-25T12:34:56.789Z rest")
    assert v == int(datetime(2026, 7, 25, 12, 34, 56, 789000, tzinfo=timezone.utc).timestamp() * 1000)


def test_ts_iso_offset():
    v = parse_ts_ms("2026-07-25T15:34:56+03:00 [INFO] x")
    assert v == int(datetime(2026, 7, 25, 12, 34, 56, tzinfo=timezone.utc).timestamp() * 1000)


def test_ts_iso_date_time_tokens_comma_ms():
    # uvicorn-формат: «2026-07-25 12:34:56,789 [INFO] ...» (локальное время)
    v = parse_ts_ms("2026-07-25 12:34:56,789 [INFO] hello")
    assert v == _local_ms(2026, 7, 25, 12, 34, 56, 789000)


def test_ts_vllm_md_date():
    # vLLM: «07-10 12:00:00» без года → текущий год, локальное время
    v = parse_ts_ms("07-10 12:00:00 [vllm] Engine00: Running: 1 reqs")
    assert v == _local_ms(NOW.year, 7, 10, 12, 0, 0)


def test_ts_syslog():
    v = parse_ts_ms("Sep 25 12:34:56 systemd[1]: started")
    exp = datetime(NOW.year, 9, 25, 12, 34, 56, tzinfo=LOCAL_TZ)
    if exp > NOW + timedelta(days=2):
        exp = exp.replace(year=NOW.year - 1)
    assert v == int(exp.timestamp() * 1000)


def test_ts_epoch_seconds_and_ms():
    assert parse_ts_ms("1756200000 INFO x") == 1756200000 * 1000
    assert parse_ts_ms("1756200000.123 INFO x") == 1756200000 * 1000 + 123
    assert parse_ts_ms("1756200000123 x") == 1756200000123


def test_ts_none_for_garbage():
    assert parse_ts_ms("no timestamp here at all") is None
    assert parse_ts_ms("") is None


# --------------------------------------------------------------- уровни

def test_levels():
    assert parse_level("[INFO] hello") == "INFO"
    assert parse_level("2026-07-25T12:00:00Z WARNING: disk almost full") == "WARNING"
    assert parse_level("Sep 25 12:34:56 app[1]: WARN: retrying") == "WARNING"
    assert parse_level("ERROR: boom") == "ERROR"
    assert parse_level("2026-07-25 12:00:00,000 [ERR] short") == "ERROR"
    assert parse_level("CRITICAL: meltdown") == "CRITICAL"
    assert parse_level("FATAL: unhandled") == "CRITICAL"
    assert parse_level("2026-07-25 12:00:00 DEBUG: probe") == "DEBUG"
    # строки без уровня (stdout-мусор) → INFO
    assert parse_level("just some plain stdout output") == "INFO"
    assert parse_level("") == "INFO"


def test_normalize_level():
    assert normalize_level("warn") == "WARNING"
    assert normalize_level("Err") == "ERROR"
    assert normalize_level("FATAL") == "CRITICAL"
    assert normalize_level("bogus") == "INFO"
    assert set(LEVELS) == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def test_parse_line_fallback_ts():
    received = 1_780_000_000_123
    ts, level = parse_line("plain garbage line", received)
    assert ts == received
    assert level == "INFO"


# ------------------------------------------------------------- stat-паттерны

VLLM_STAT_LINE = (
    "07-10 12:00:00 [vllm] Engine00: Running: 3 reqs, Waiting: 2 reqs, "
    "GPU KV cache usage: 12.3%, Prefix cache hit rate: 4.5%"
)


def test_vllm_stat_full():
    stats = parse_vllm_stat(VLLM_STAT_LINE)
    assert stats == {
        "running": 3,
        "waiting": 2,
        "kv_cache_pct": 12.3,
        "prefix_cache_hit_rate_pct": 4.5,
    }


def test_vllm_stat_throughput():
    line = (
        "INFO 07-10 12:00:05 [vllm] Engine00: Avg prompt throughput: 45.1 toks/s, "
        "Avg generation throughput: 12.4 toks/s"
    )
    stats = parse_vllm_stat(line)
    assert stats == {
        "avg_prompt_throughput": 45.1,
        "avg_generation_throughput": 12.4,
    }


def test_vllm_stat_none_for_plain_lines():
    assert parse_vllm_stat("INFO: 127.0.0.1 - GET /metrics 200") is None
    assert parse_vllm_stat("") is None
