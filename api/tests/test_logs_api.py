"""REST API логов (F3): фильтры, LIKE-экранирование, пагинация, desc,
stats, export (txt/csv), sources, health, SSE /api/logs/live.

SSE-тест — настоящий uvicorn в треде на СЛУЧАЙНОМ порту (не на :8100).
"""

import json
import re
import time
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, LogSource, LogSources, Sources, Storage
from app.main import create_app
from conftest import seed_log_entries

NOW = int(time.time())
DAY = 86400
STAT_LINE = (
    "Engine00: Running: 3 reqs, Waiting: 2 reqs, "
    "GPU KV cache usage: 12.3%, Prefix cache hit rate: 4.5%"
)


@pytest.fixture
def app(db_path):
    cfg = AppConfig(
        sources=Sources(
            logs=LogSources(
                sources=[
                    LogSource(name="vllm", type="file", path="/tmp/nope.log"),
                    LogSource(name="vllm2", type="docker", container="vllm"),
                ],
                retention_days=14,
            )
        ),
        storage=Storage(sqlite_path=str(db_path)),
        start_pollers=False,
    )
    return create_app(config=cfg, start_pollers=False)


@pytest.fixture
def client(app, db_path):
    with TestClient(app) as c:
        yield c


def _seed_basic(db_path):
    seed_log_entries(
        db_path,
        [
            (NOW * 1000 - 5000, "INFO", "uvicorn hello", "vllm"),
            (NOW * 1000 - 4000, "ERROR", "boom error", "vllm"),
            (NOW * 1000 - 3000, "WARNING", "disk almost full", "vllm"),
            (NOW * 1000 - 2000, "INFO", "usage 100% done", "vllm"),
            (NOW * 1000 - 1500, "INFO", "row a_b underscore", "vllm"),
            (NOW * 1000 - 1000, "INFO", "row axb other", "vllm"),
            (NOW * 1000 - 500, "INFO", STAT_LINE, "vllm2"),
        ],
    )


# ---------------------------------------------------------------------- basic
def test_logs_page_desc_and_stats_field(client, db_path):
    _seed_basic(db_path)
    r = client.get(
        "/api/logs",
        params={"from": NOW - 60, "to": NOW + 60, "limit": 100},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7
    assert body["has_more"] is False
    # новые сверху (ts desc)
    assert body["rows"][0]["line"] == STAT_LINE
    assert [row["ts"] for row in body["rows"]] == sorted(
        (row["ts"] for row in body["rows"]), reverse=True
    )
    # ts — мс; stats — парсинг на бэке
    assert body["rows"][0]["stats"] == {
        "running": 3,
        "waiting": 2,
        "kv_cache_pct": 12.3,
        "prefix_cache_hit_rate_pct": 4.5,
    }
    assert body["rows"][0]["source"] == "vllm2"
    for row in body["rows"][1:]:
        assert row["stats"] is None


def test_logs_level_csv_and_source_filters(client, db_path):
    _seed_basic(db_path)
    r = client.get(
        "/api/logs",
        params={
            "from": NOW - 60,
            "to": NOW + 60,
            "level": "ERROR,WARN",
            "limit": 100,
        },
    )
    body = r.json()
    # WARN — псевдоним WARNING
    assert body["total"] == 2
    assert {row["level"] for row in body["rows"]} == {"ERROR", "WARNING"}

    r = client.get(
        "/api/logs",
        params={"from": NOW - 60, "to": NOW + 60, "source": "vllm2", "limit": 100},
    )
    body = r.json()
    assert body["total"] == 1
    assert body["rows"][0]["source"] == "vllm2"

    # неизвестный уровень → 400
    assert (
        client.get(
            "/api/logs", params={"from": NOW - 60, "to": NOW + 60, "level": "BOGUS"}
        ).status_code
        == 400
    )
    # недопустимый limit → 400
    assert (
        client.get(
            "/api/logs", params={"from": NOW - 60, "to": NOW + 60, "limit": 77}
        ).status_code
        == 400
    )


def test_logs_query_like_escaping(client, db_path):
    _seed_basic(db_path)
    # «%» в запросе — литерал, а не wildcard
    body = client.get(
        "/api/logs",
        params={"from": NOW - 60, "to": NOW + 60, "query": "100%", "limit": 100},
    ).json()
    assert body["total"] == 1
    assert "100%" in body["rows"][0]["line"]

    # «_» в запросе — литерал, не матчит «axb»
    body = client.get(
        "/api/logs",
        params={"from": NOW - 60, "to": NOW + 60, "query": "a_b", "limit": 100},
    ).json()
    assert body["total"] == 1
    assert "a_b" in body["rows"][0]["line"]


def test_logs_pagination(client, db_path):
    seed_log_entries(
        db_path,
        [(NOW * 1000 - (150 - i) * 1000, "INFO", f"line {i}", "vllm") for i in range(150)],
    )
    r = client.get(
        "/api/logs",
        params={"from": NOW - 200, "to": NOW + 60, "limit": 100, "offset": 0},
    )
    body = r.json()
    assert body["total"] == 150
    assert len(body["rows"]) == 100
    assert body["has_more"] is True
    assert body["rows"][0]["line"] == "line 149"  # новая сверху
    assert body["rows"][-1]["line"] == "line 50"

    body = client.get(
        "/api/logs",
        params={"from": NOW - 200, "to": NOW + 60, "limit": 100, "offset": 100},
    ).json()
    assert len(body["rows"]) == 50
    assert body["has_more"] is False
    assert body["rows"][0]["line"] == "line 49"
    assert body["rows"][-1]["line"] == "line 0"

    # page-size 250/500 — допустимые
    assert (
        client.get(
            "/api/logs", params={"from": NOW - 60, "to": NOW + 60, "limit": 250}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/logs", params={"from": NOW - 60, "to": NOW + 60, "limit": 500}
        ).status_code
        == 200
    )


# ----------------------------------------------------------------------- stats
def test_logs_stats(client, db_path):
    today = date.today()
    off = int(datetime.now().astimezone().utcoffset().total_seconds())

    def local_midnight(d: date) -> int:
        return int(datetime(d.year, d.month, d.day).astimezone().timestamp())

    d1, d2 = today - timedelta(days=1), today + timedelta(days=1)
    rows = [
        (local_midnight(d1) * 1000 + 60_000, "INFO", "y1-1", "vllm"),
        (local_midnight(d1) * 1000 + 120_000, "ERROR", "y1-2", "vllm"),
        (local_midnight(today) * 1000 + 60_000, "INFO", "t-1", "vllm"),
        (local_midnight(today) * 1000 + 120_000, "WARNING", "t-2", "vllm"),
        (local_midnight(today) * 1000 + 180_000, "ERROR", "t-3", "vllm"),
        (local_midnight(d2) * 1000 + 60_000, "DEBUG", "y2-1", "vllm"),
    ]
    seed_log_entries(db_path, rows)

    frm = local_midnight(today - timedelta(days=2))
    to = local_midnight(d2) + 3600
    body = client.get("/api/logs/stats", params={"from": frm, "to": to}).json()
    by_day = {e["day"]: e for e in body["by_day"]}
    assert len(body["by_day"]) == 4  # все дни окна [today-2d .. today+1d], включая пустой
    assert by_day[local_midnight(d1)]["levels"]["ERROR"] == 1
    assert by_day[local_midnight(d1)]["total"] == 2
    assert by_day[local_midnight(today)]["levels"]["ERROR"] == 1
    assert by_day[local_midnight(today)]["levels"]["WARNING"] == 1
    assert by_day[local_midnight(today)]["total"] == 3
    assert by_day[local_midnight(d2)]["levels"]["DEBUG"] == 1
    # пустые дни — нули по всем уровням
    empty = [e for e in body["by_day"] if e["total"] == 0]
    assert len(empty) == 1
    assert all(set(e["levels"]) == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} for e in empty)
    # «day» — локальная полночь (с offset'ом сервера)
    assert (body["by_day"][0]["day"] + off) % 86400 == 0


# ---------------------------------------------------------------------- export
def test_logs_export_txt(client, db_path):
    _seed_basic(db_path)
    r = client.get(
        "/api/logs/export",
        params={"from": NOW - 60, "to": NOW + 60, "format": "txt", "limit": 100},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert 'attachment; filename="llm-logs-' in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert len(lines) == 7
    for ln in lines:
        assert re.match(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
            r"(DEBUG|INFO|WARNING|ERROR|CRITICAL) +\[(vllm|vllm2)\] ",
            ln,
        ), ln
    assert "[vllm2]" in lines[0] and STAT_LINE in lines[0]
    assert lines[-1].endswith("uvicorn hello")


def test_logs_export_csv(client, db_path):
    _seed_basic(db_path)
    r = client.get(
        "/api/logs/export",
        params={"from": NOW - 60, "to": NOW + 60, "format": "csv", "limit": 3},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "ts,level,source,line"
    assert len(lines) == 1 + 3  # limit=3
    # строки с запятыми/кавычками экранируются csv
    r = client.get(
        "/api/logs/export",
        params={
            "from": NOW - 60,
            "to": NOW + 60,
            "format": "csv",
            "query": STAT_LINE.split(",")[0],  # «Running: 3 reqs»
        },
    )
    body_lines = r.text.strip().splitlines()
    assert len(body_lines) == 2
    assert "Running: 3 reqs" in body_lines[1]
    assert '"' in body_lines[1]  # поле line с запятыми — в кавычках


# --------------------------------------------------------------------- sources
def test_logs_sources_and_health(client, app):
    body = client.get("/api/logs/sources").json()
    assert [s["name"] for s in body["sources"]] == ["vllm", "vllm2"]
    assert body["sources"][0]["type"] == "file"
    assert body["sources"][1]["container"] == "vllm"
    assert body["sources"][0]["status"] == "unknown"  # tailer не запускался

    health = client.get("/api/health").json()
    assert "logs.vllm" in health["sources"]
    assert "logs.vllm2" in health["sources"]


# ------------------------------------------------------------------------- SSE
@pytest.fixture
def live_server(app, db_path):
    """uvicorn в треде на случайном порту (TestClient не умеет SSE-стриминг)."""
    import threading

    import uvicorn

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    deadline = time.time() + 15
    while not server.started:
        assert time.time() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    inner = server.servers[0]
    socks = getattr(inner, "sockets", None)
    port = (socks[0] if socks else inner).getsockname()[1]
    yield {"port": port, "app": app}
    server.should_exit = True
    th.join(timeout=10)


def test_logs_live_sse(live_server, db_path):
    import httpx

    app = live_server["app"]
    # буфер, как если бы tailer проиндексировал строки
    entries = [
        {"id": i + 1, "ts": NOW * 1000 + i, "source": "vllm",
         "level": "INFO" if i < 2 else "ERROR", "line": f"live line {i}"}
        for i in range(3)
    ]
    app.state.log_buffer.add_many(entries)

    url = f"http://127.0.0.1:{live_server['port']}/api/logs/live"
    with httpx.Client(timeout=httpx.Timeout(20)) as client:
        with client.stream("GET", url) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            got = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                if len(got) == 3:
                    break
    assert [e["line"] for e in got] == ["live line 0", "live line 1", "live line 2"]
    assert all(set(e) == {"ts", "source", "level", "line"} for e in got)

    # дедупликация по id: повторное подключение не даст повторных id ≤ последних
    seen_ids = [e["ts"] for e in got]
    with httpx.Client(timeout=httpx.Timeout(20)) as client:
        with client.stream("GET", url) as r:
            again = []
            for line in r.iter_lines():
                if line.startswith("data: "):
                    again.append(json.loads(line[6:]))
                if len(again) == 3:
                    break
    # те же 3 строки (буфер ring, id монотонны) — без дублей внутри ответа
    assert len({e["ts"] for e in again}) == 3
    assert again[0]["line"] == "live line 0"
    assert seen_ids == [NOW * 1000 + i for i in range(3)]
