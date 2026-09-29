"""Тесты REST API F0/F1 (офлайн, TestClient, pollers выключены)."""

import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from conftest import seed_samples

NOW = int(time.time())


@pytest.fixture
def live_server(make_app, db_path):
    """Настоящий uvicorn (в тред, случайный порт): TestClient этого starlette
    буферизует ответ целиком и не умеет SSE-стриминг, поэтому /api/live
    тестируется по настоящему HTTP-подключению."""
    import threading
    import time as _time

    import uvicorn

    app = make_app()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    deadline = _time.time() + 15
    while not server.started:
        assert _time.time() < deadline, "uvicorn did not start"
        _time.sleep(0.05)
    inner = server.servers[0]
    socks = getattr(inner, "sockets", None)
    port = (socks[0] if socks else inner).getsockname()[1]
    yield {"port": port, "app": app}
    server.should_exit = True
    th.join(timeout=10)


def _conn(db_path):
    return sqlite3.connect(str(db_path))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"]
    assert set(body["sources"]) == {"vllm", "gpu", "system"}
    for st in body["sources"].values():
        assert st["status"] == "unknown"  # pollers не запускались


def test_throttle_names_decoding():
    """issue #2: ключи THROTTLE_REASON_NAMES — значения битов (1, 2, 4, …);
    bit 0 должен декодироваться, имена — по значению, а не позиции."""
    from app.api.routes import _throttle_names

    assert _throttle_names(1) == ["gpu_slowdown"]
    assert _throttle_names(2) == ["sync_boost"]
    assert _throttle_names(4) == ["sw_power_brake"]
    assert _throttle_names(5) == ["gpu_slowdown", "sw_power_brake"]
    assert _throttle_names(128) == ["sw power cap"]
    assert _throttle_names(129) == ["gpu_slowdown", "sw power cap"]
    # биты выше 128 — не декодируются (как раньше: только 2^0…2^7)
    assert _throttle_names(256) == []
    assert _throttle_names(0) == []
    assert _throttle_names(None) == []
    assert _throttle_names(1.0) == ["gpu_slowdown"]  # из БД float


def test_metrics_raw(client, db_path):
    seed_samples(db_path, [
        ("cpu_usage", NOW - 3600 + i, float(i), "system", None, None)
        for i in range(100)
    ])
    r = client.get(
        "/api/metrics/cpu_usage", params={"from": NOW - 3610, "to": NOW + 60}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "raw"
    assert body["count"] == 100
    assert body["points"][0] == [NOW - 3600, 0.0]


def test_metrics_raw_gpu_filter(client, db_path):
    seed_samples(db_path, [
        ("gpu_power", NOW - 100, 250.0, "gpu", 0, None),
        ("gpu_power", NOW - 100, 999.0, "gpu", 1, None),
    ])
    body = client.get("/api/metrics/gpu_power", params={"gpu": 1}).json()
    assert body["count"] == 1
    assert body["points"][0][1] == 999.0


def test_metrics_downsampled(client, db_path):
    seed_samples(db_path, [
        ("m", NOW - 3600 + i, float(i % 7), "system", None, None)
        for i in range(5000)
    ])
    body = client.get("/api/metrics/m").json()
    assert body["source"] == "raw"
    assert body["count"] <= 1500


def test_metrics_hourly(client, db_path):
    c = _conn(db_path)
    for i in range(24 * 7):
        c.execute(
            "INSERT INTO metric_hourly (metric, hour, avg, min, max, p95, count) "
            "VALUES ('m', ?, ?, 0, 1, 1, 12)",
            (NOW - 7 * 86400 + i * 3600, 0.5),
        )
    c.commit()
    c.close()
    body = client.get(
        "/api/metrics/m", params={"from": NOW - 7 * 86400, "to": NOW}
    ).json()
    assert body["source"] == "hourly"
    assert body["count"] == 24 * 7


def test_metrics_hourly_multigpu(client, db_path):
    # gpu-метрики: без gpu — среднее по строкам gpu; с gpu=N — только эта gpu
    c = _conn(db_path)
    base = (NOW - 3 * 86400) // 3600 * 3600
    for i in range(24 * 3):
        for gpu, w in ((0, 300.0), (1, 200.0)):
            c.execute(
                "INSERT INTO metric_hourly (metric, hour, gpu, avg, min, max, p95, count) "
                "VALUES ('gpu_power', ?, ?, ?, ?, ?, ?, 12)",
                (base + i * 3600, gpu, w, w, w, w),
            )
    c.commit()
    c.close()
    params = {"from": NOW - 3 * 86400, "to": NOW}
    body = client.get("/api/metrics/gpu_power", params=params).json()
    assert body["source"] == "hourly"
    assert body["count"] == 24 * 3
    assert all(p[1] == 250.0 for p in body["points"])  # (300+200)/2
    body = client.get(
        "/api/metrics/gpu_power", params={**params, "gpu": 1}
    ).json()
    assert body["count"] == 24 * 3
    assert all(p[1] == 200.0 for p in body["points"])


def test_metrics_daily(client, db_path):
    c = _conn(db_path)
    for i in range(30):
        c.execute(
            "INSERT INTO metric_daily (metric, day, avg, min, max, p95, sum, count) "
            "VALUES ('m', ?, 1, 0, 2, 1.5, 120, 120)",
            (NOW - 30 * 86400 + i * 86400,),
        )
    c.commit()
    c.close()
    body = client.get(
        "/api/metrics/m", params={"from": NOW - 30 * 86400, "to": NOW}
    ).json()
    assert body["source"] == "daily"
    assert body["count"] == 30


def test_metrics_raw_fallback_to_hourly(client, db_path):
    # сырых нет (ретенция), но hourly за последний час есть
    c = _conn(db_path)
    c.execute(
        "INSERT INTO metric_hourly (metric, hour, avg) VALUES ('m', ?, 7.5)",
        ((NOW // 3600) * 3600,),
    )
    c.commit()
    c.close()
    body = client.get("/api/metrics/m").json()
    assert body["source"] == "hourly"
    assert body["points"][0][1] == 7.5


def test_metrics_empty(client):
    body = client.get("/api/metrics/does_not_exist").json()
    assert body["count"] == 0
    assert body["points"] == []


def _seed_gpu(db_path):
    seed_samples(db_path, [
        ("gpu_power", NOW - 10, 300.0, "gpu", 0, None),
        ("gpu_power", NOW - 10, 400.0, "gpu", 1, None),
        ("gpu_mem_used_mib", NOW - 10, 1000.0, "gpu", 0, None),
        ("gpu_mem_used_mib", NOW - 10, 2000.0, "gpu", 1, None),
        ("gpu_mem_total_mib", NOW - 10, 16384.0, "gpu", 0, None),
        ("gpu_mem_total_mib", NOW - 10, 16384.0, "gpu", 1, None),
        ("num_requests_running", NOW - 5, 2.0, "vllm", None, "qwen3.8-27b-dflash2"),
    ])
    c = _conn(db_path)
    c.execute(
        "INSERT INTO gpu_devices (id, name, total_mem_mib, pci_bus) "
        "VALUES (0, 'RTX 5070 Ti', 16384, '0000:41:00.0'), "
        "(1, 'RTX 5070 Ti', 16384, '0000:42:00.0')"
    )
    c.commit()
    c.close()


def test_overview(client, db_path):
    _seed_gpu(db_path)
    body = client.get("/api/overview").json()
    assert body["model"] == "qwen3.8-27b-dflash2"
    assert body["total_power_w"] == pytest.approx(700.0)
    assert body["total_mem_used_mib"] == pytest.approx(3000.0)
    assert body["total_mem_mib"] == pytest.approx(32768.0)
    assert body["vllm"]["num_requests_running"] == 2.0
    assert len(body["gpus"]) == 2
    assert body["gpus"][0]["name"] == "RTX 5070 Ti"
    assert body["gpus"][1]["power_w"] == 400.0


def test_gpus(client, db_path):
    _seed_gpu(db_path)
    body = client.get("/api/gpus").json()
    assert body["live"] is False
    assert [g["id"] for g in body["gpus"]] == [0, 1]
    g0 = body["gpus"][0]
    assert g0["power_w"] == 300.0
    assert g0["mem_used_mib"] == 1000.0
    assert g0["mem_total_mib"] == 16384.0
    assert g0["throttle_reason_names"] == []


def test_gpus_live_without_driver(client, db_path):
    # live=true без NVML (в тесте gpu_collector не создан) → снимок из БД
    _seed_gpu(db_path)
    body = client.get("/api/gpus", params={"live": "true"}).json()
    assert body["live"] is True
    assert len(body["gpus"]) == 2


def test_system(client, db_path):
    seed_samples(db_path, [
        ("cpu_usage", NOW - 10, 12.5, "system", None, None),
        ("cpu_usage_core_0", NOW - 10, 30.0, "system", None, None),
        ("cpu_usage_core_1", NOW - 10, 15.0, "system", None, None),
        ("load_avg_1", NOW - 10, 0.5, "system", None, None),
        ("ram_total_mb", NOW - 10, 65536.0, "system", None, None),
        ("ram_used_mb", NOW - 10, 20000.0, "system", None, None),
        ("disk_used_pct|/", NOW - 10, 42.0, "system", None, None),
        ("disk_used_pct|/mnt", NOW - 10, 77.0, "system", None, None),
        ("psi_cpu_avg10", NOW - 10, 1.1, "system", None, None),
        ("psi_memory_avg60", NOW - 10, 0.2, "system", None, None),
        ("net_rx_mbps", NOW - 10, 100.0, "system", None, None),
    ])
    body = client.get("/api/system").json()
    assert body["cpu"]["usage"] == 12.5
    assert body["cpu"]["per_core"] == [30.0, 15.0]  # по номеру ядра
    assert body["cpu"]["load"][0] == 0.5
    assert body["ram"]["used_mb"] == 20000.0
    assert {d["mount"] for d in body["disks"]} == {"/", "/mnt"}
    assert body["psi"]["cpu"]["avg10"] == 1.1
    assert body["psi"]["memory"]["avg60"] == 0.2
    assert body["net"]["rx_mbps"] == 100.0
    # issue #3: top_cpu/top_ram убраны (в контейнере виден только uvicorn)
    assert "top_cpu" not in body and "top_ram" not in body


def _read_packets(server, n):
    """Читает n SSE-пакетов из /api/live (реальный http-клиент, стриминг)."""
    import httpx

    with httpx.Client(
        base_url=f"http://127.0.0.1:{server['port']}", timeout=15
    ) as c:
        with c.stream("GET", "/api/live") as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            packets, retry_seen = [], False
            for line in r.iter_lines():
                if line.startswith("retry:"):
                    retry_seen = True
                if line.startswith("data: "):
                    packets.append(json.loads(line[len("data: ") :]))
                if len(packets) >= n:
                    break
            assert retry_seen
    return packets


def test_live_sse_format_offline(live_server, monkeypatch):
    # pollers не запускались → источники offline, блоки null, но пакет слан
    from app.api import routes

    monkeypatch.setattr(routes, "LIVE_INTERVAL_S", 0.2)
    packets = _read_packets(live_server, 2)
    assert len(packets) == 2
    for p in packets:
        assert set(p) == {"ts", "sources", "model", "kpi", "gpu_total", "gpus", "system", "alerts_active"}
        assert set(p["sources"]) == {"vllm", "gpu", "system"}
        for st in p["sources"].values():
            assert st in ("ok", "offline")
        assert p["sources"] == {"vllm": "offline", "gpu": "offline", "system": "offline"}
        assert p["model"] is None
        assert p["kpi"] is None
        assert p["gpu_total"] is None
        assert p["gpus"] is None
        assert p["system"] is None
        assert p["alerts_active"] == 0
        assert isinstance(p["ts"], int)


def test_live_sse_packet_from_snapshots(live_server, monkeypatch):
    # кэш снимков заполнен + источники online → блоки по контракту
    from app.api import routes

    monkeypatch.setattr(routes, "LIVE_INTERVAL_S", 0.2)
    app = live_server["app"]
    app.state.snapshots["vllm"] = {
        "ts": NOW,
        "model": "qwen3.8-27b-dflash2",
        "metrics": {
            "num_requests_running": 3.0,
            "num_requests_waiting": 0.0,
            "prompt_tokens_rate": 12.4,
            "generation_tokens_rate": 34.1,
            "kv_cache_usage": 42.0,
            "prefix_cache_hits_rate": 1.2,
            "prefix_cache_queries_rate": 10.0,
            "ttft_p95": 0.42,
            "tpot_p95": 0.021,
            "e2e_latency_p95": 1.8,
            "num_preemptions_rate": 0.0,
        },
    }
    app.state.snapshots["gpu"] = {
        "ts": NOW,
        "gpus": {
            0: {
                "id": 0,
                "name": "RTX 5070 Ti",
                "power_w": 72.0,
                "power_limit_w": 300.0,
                "util": 43.0,
                "mem_used_mib": 14620.0,
                "mem_total_mib": 16303.0,
                "temp": 43.0,
                "sm_clock_mhz": 1500.0,
                "mem_clock_mhz": 1313.0,
                "throttle": 0,
                "ecc_correctable": 0.0,
                "ecc_uncorrectable": 0.0,
            }
        },
    }
    app.state.snapshots["system"] = {
        "ts": NOW,
        "metrics": {
            "cpu_usage": 12.5,
            "load_avg_1": 1.2,
            "ram_used_mb": 8192.0,
            "ram_total_mb": 65536.0,
        },
    }
    app.state.statuses["vllm"].ok()
    app.state.statuses["gpu"].ok()
    app.state.statuses["system"].ok()

    packets = _read_packets(live_server, 1)
    p = packets[0]
    assert p["sources"] == {"vllm": "ok", "gpu": "ok", "system": "ok"}
    assert p["model"] == "qwen3.8-27b-dflash2"
    kpi = p["kpi"]
    assert kpi["running"] == 3.0
    assert kpi["prompt_rate"] == 12.4
    assert kpi["gen_rate"] == 34.1
    assert kpi["kv_cache"] == 42.0
    assert kpi["prefix_hit_rate"] == pytest.approx(0.12)
    assert kpi["ttft_p95"] == 0.42
    assert kpi["tpot_p95"] == 0.021
    assert kpi["e2e_p95"] == 1.8
    assert kpi["preemptions_rate"] == 0.0
    assert p["gpu_total"] == {"power_w": 72.0, "mem_used_mib": 14620.0, "mem_total_mib": 16303.0}
    g0 = p["gpus"][0]
    assert set(g0) == {
        "id", "name", "power_w", "power_limit_w", "mem_used_mib", "mem_total_mib",
        "util", "temp", "sm_clock_mhz", "mem_clock_mhz", "throttle",
        "ecc_correctable", "ecc_uncorrectable",
    }
    assert g0["id"] == 0 and g0["power_limit_w"] == 300.0 and g0["throttle"] == []
    assert p["system"] == {"cpu": 12.5, "load1": 1.2, "ram_used_mib": 8192.0, "ram_total_mib": 65536.0}


def test_live_sse_prefix_hit_rate_rolling(live_server, monkeypatch):
    # «Холодное» 5-с окно (hits_rate=0): карточка берёт rolling ~60 с из снимка
    from app.api import routes

    monkeypatch.setattr(routes, "LIVE_INTERVAL_S", 0.2)
    app = live_server["app"]
    app.state.snapshots["vllm"] = {
        "ts": NOW,
        "model": "m",
        "metrics": {
            "prefix_cache_hits_rate": 0.0,
            "prefix_cache_queries_rate": 10.0,
            "prefix_hit_rate_60s": 0.82,
        },
    }
    app.state.statuses["vllm"].ok()

    packets = _read_packets(live_server, 1)
    assert packets[0]["kpi"]["prefix_hit_rate"] == pytest.approx(0.82)


def test_live_sse_token_rates_60s_fallback(live_server, monkeypatch):
    """issue #1: live prompt_rate/gen_rate берут rolling ~60 с из снимка,
    при его отсутствии — 5-с rate, если и его нет — null."""
    from app.api import routes

    monkeypatch.setattr(routes, "LIVE_INTERVAL_S", 0.2)
    app = live_server["app"]
    app.state.snapshots["vllm"] = {
        "ts": NOW,
        "model": "m",
        "metrics": {
            "prompt_tokens_rate": 90000.0,
            "generation_tokens_rate": 60.0,
            "prompt_tokens_rate_60s": 1393.8,
            "generation_tokens_rate_60s": 2.3,
        },
    }
    app.state.statuses["vllm"].ok()
    kpi = _read_packets(live_server, 1)[0]["kpi"]
    assert kpi["prompt_rate"] == pytest.approx(1393.8)  # 60s, а не всплеск 90000
    assert kpi["gen_rate"] == pytest.approx(2.3)

    # без 60s-значений → fallback на 5-с rate
    app.state.snapshots["vllm"]["metrics"] = {
        "prompt_tokens_rate": 12.4,
        "generation_tokens_rate": 34.1,
    }
    kpi = _read_packets(live_server, 1)[0]["kpi"]
    assert kpi["prompt_rate"] == pytest.approx(12.4)
    assert kpi["gen_rate"] == pytest.approx(34.1)


def test_live_sse_mixed_sources_offline(live_server, monkeypatch):
    # vLLM online, GPU/system offline → их блоки null
    from app.api import routes

    monkeypatch.setattr(routes, "LIVE_INTERVAL_S", 0.2)
    app = live_server["app"]
    app.state.snapshots["vllm"] = {
        "ts": NOW,
        "model": "m",
        "metrics": {"num_requests_running": 1.0},
    }
    app.state.statuses["vllm"].ok()

    packets = _read_packets(live_server, 1)
    p = packets[0]
    assert p["sources"] == {"vllm": "ok", "gpu": "offline", "system": "offline"}
    assert p["kpi"]["running"] == 1.0
    assert p["gpus"] is None and p["gpu_total"] is None and p["system"] is None


def test_metrics_model_filter_hourly(client, db_path):
    # F4.4: фильтр модели на периоде >24ч — из metric_hourly (не только raw 168ч)
    c = _conn(db_path)
    for i in range(24 * 7):
        c.execute(
            "INSERT INTO metric_hourly (metric, hour, model, avg, min, max, p95, count) "
            "VALUES ('m', ?, 'model-a', ?, 0, 1, 1, 12)",
            (NOW - 7 * 86400 + i * 3600, 0.5),
        )
        c.execute(
            "INSERT INTO metric_hourly (metric, hour, model, avg, min, max, p95, count) "
            "VALUES ('m', ?, 'model-b', ?, 0, 1, 1, 12)",
            (NOW - 7 * 86400 + i * 3600, 9.0),
        )
    c.commit()
    c.close()
    body = client.get(
        "/api/metrics/m",
        params={"from": NOW - 7 * 86400, "to": NOW, "model": "model-a"},
    ).json()
    assert body["source"] == "hourly"
    assert body["count"] == 24 * 7
    assert all(p[1] == 0.5 for p in body["points"])
    # чужая модель — не попадает
    body_b = client.get(
        "/api/metrics/m",
        params={"from": NOW - 7 * 86400, "to": NOW, "model": "model-b"},
    ).json()
    assert all(p[1] == 9.0 for p in body_b["points"])
