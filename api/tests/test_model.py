"""Тесты GET /api/model (docs/api-contracts.md): сегментация моделей,
диффы счётчиков/finish reasons/distributions, квантили (raw + hourly)."""

import time

import pytest
from fastapi.testclient import TestClient

from conftest import seed_samples

NOW = int(time.time())

# --- синтетика: две модели в одном периоде (F1: сегментация)
P0, P1 = 1_000, 2_999  # период [1000, 2999]
M_A, M_B = "model-a", "model-b"


def _seed_two_models(db_path):
    v = "vllm"
    seed_samples(db_path, [
        # --- сегментация: model-a на [1000,1999], model-b на [2000,2999]
        ("num_requests_running", 1000, 2.0, v, None, M_A),
        ("num_requests_running", 1999, 3.0, v, None, M_A),
        ("num_requests_running", 2999, 3.0, v, None, M_B),
        ("num_requests_waiting", 1500, 1.0, v, None, M_A),
        ("num_requests_waiting", 2000, 1.0, v, None, M_B),
        ("num_requests_waiting", 2500, 0.0, v, None, M_B),
        ("kv_cache_usage", 2999, 42.0, v, None, M_B),
        # --- rates (средние за период): 10/20 → 15; 30 → 30
        ("prompt_tokens_rate", 1500, 10.0, v, None, M_A),
        ("prompt_tokens_rate", 2500, 20.0, v, None, M_B),
        ("generation_tokens_rate", 1500, 30.0, v, None, M_A),
        # --- сырые квантили: ttft p50/p95
        ("ttft_p50", 1400, 0.2, v, None, M_A),
        ("ttft_p50", 1600, 0.4, v, None, M_A),
        ("ttft_p95", 1400, 0.4, v, None, M_A),
        ("ttft_p95", 1600, 0.8, v, None, M_A),
        # tpot — по одной точке каждого квантиля
        ("tpot_p50", 1400, 0.02, v, None, M_A),
        ("tpot_p95", 1400, 0.05, v, None, M_A),
        # e2e: p95 из точек 1.5/2.5 → 2.45
        ("e2e_latency_p95", 1400, 1.5, v, None, M_A),
        ("e2e_latency_p95", 1600, 2.5, v, None, M_A),
        # --- счётчики (дифф за период)
        ("prefix_cache_queries_total", 1500, 100.0, v, None, M_A),
        ("prefix_cache_queries_total", 2500, 200.0, v, None, M_B),
        ("prefix_cache_hits_total", 1500, 10.0, v, None, M_A),
        ("prefix_cache_hits_total", 2500, 30.0, v, None, M_B),
        ("num_preemptions_total", 1500, 1.0, v, None, M_A),
        ("num_preemptions_total", 2500, 5.0, v, None, M_B),
        # finish reasons
        ("request_success_total_stop", 1500, 50.0, v, None, M_A),
        ("request_success_total_stop", 2500, 150.0, v, None, M_B),
        ("request_success_total_length", 1500, 10.0, v, None, M_A),
        ("request_success_total_length", 2500, 12.0, v, None, M_B),
        # --- distributions (Δ bucket-счётчиков)
        ("request_prompt_tokens_bucket_16", 1500, 100.0, v, None, M_A),
        ("request_prompt_tokens_bucket_16", 2500, 500.0, v, None, M_B),
        ("request_prompt_tokens_bucket_32", 1500, 0.0, v, None, M_A),
        ("request_prompt_tokens_bucket_32", 2500, 300.0, v, None, M_B),
        ("request_prompt_tokens_bucket_64", 1500, 50.0, v, None, M_A),
        ("request_prompt_tokens_bucket_64", 2500, 50.0, v, None, M_B),
        ("request_generation_tokens_bucket_16", 1500, 20.0, v, None, M_A),
        ("request_generation_tokens_bucket_16", 2500, 220.0, v, None, M_B),
    ])


@pytest.fixture
def client(make_app, db_path):
    app = make_app()
    with TestClient(app) as c:
        yield c


def test_model_two_models(client, db_path):
    _seed_two_models(db_path)
    body = client.get("/api/model", params={"from": P0, "to": P1}).json()

    # сегментация по метке model
    assert body["models"] == [
        {"name": M_A, "from": 1000, "to": 1999},
        {"name": M_B, "from": 2000, "to": 2999},
    ]

    kpi = body["kpi"]
    assert kpi["running"] == 3.0  # последнее значение в периоде
    assert kpi["waiting"] == 0.0
    assert kpi["kv_cache"] == 42.0
    assert kpi["prompt_rate"] == pytest.approx(15.0)
    assert kpi["gen_rate"] == pytest.approx(30.0)
    # квантили — по отдельным сериям (линейная интерполяция):
    # ttft p50: [0.2, 0.4] → 0.3; ttft p95: [0.4, 0.8] → 0.78
    assert kpi["ttft_p50"] == pytest.approx(0.3)
    assert kpi["ttft_p95"] == pytest.approx(0.78)
    # tpot p50: [0.02] → 0.02; tpot p95: [0.05] → 0.05
    assert kpi["tpot_p50"] == pytest.approx(0.02)
    assert kpi["tpot_p95"] == pytest.approx(0.05)
    # e2e: [1.5, 2.5] → p95 = 2.45
    assert kpi["e2e_p95"] == pytest.approx(2.45)
    # prefix hit rate: Δ(30-10) / Δ(200-100) = 0.2
    assert kpi["prefix_hit_rate"] == pytest.approx(0.2)
    # preemptions: Δ = 4
    assert kpi["preemptions"] == 4
    # finish reasons — дифф; requests_finished — сумма
    assert kpi["finish_reasons"] == {"stop": 100, "length": 2}
    assert kpi["requests_finished"] == 102
    # distributions — Δ bucket-счётчиков, нулевые дельты исключены
    assert body["distributions"]["prompt_tokens"] == [[16, 400], [32, 300]]
    assert body["distributions"]["generation_tokens"] == [[16, 200]]


def test_model_empty_period(client):
    body = client.get("/api/model", params={"from": 100, "to": 200}).json()
    assert body["models"] == []
    assert body["distributions"] == {"prompt_tokens": [], "generation_tokens": []}
    for v in body["kpi"].values():
        assert v in (None, {}) or v == {}


def test_model_default_period(client, db_path):
    _seed_two_models(db_path)
    # без from/to — последний час; синтетика в прошлом → пусто, но формат тот же
    body = client.get("/api/model").json()
    assert set(body) == {"models", "kpi", "distributions"}
    assert set(body["kpi"]) == {
        "running", "waiting", "prompt_rate", "gen_rate",
        "ttft_p50", "ttft_p95", "tpot_p50", "tpot_p95", "e2e_p95",
        "kv_cache", "prefix_hit_rate", "preemptions",
        "requests_finished", "finish_reasons",
    }


def test_model_hourly_period(client, db_path):
    # период >24ч — из metric_hourly (p95-колонка, avg-колонка)
    import sqlite3

    from conftest import REPO_ROOT  # noqa: F401

    c = sqlite3.connect(str(db_path))
    base = (NOW - 25 * 3600) // 3600 * 3600
    rows = [
        # (metric, avg, p95, count)
        ("prompt_tokens_rate", 10.0, None, 12),
        ("prompt_tokens_rate", 20.0, None, 12),  # взвешенное среднее = 15
        ("generation_tokens_rate", 30.0, None, 12),
        ("ttft_p50", 0.2, None, 12),
        ("ttft_p50", 0.4, None, 12),  # avg(ttft_p50) = 0.3
        ("ttft_p95", None, 0.5, 12),
        ("ttft_p95", None, 0.9, 12),  # avg(p95) = 0.7
        ("e2e_latency_p95", None, 2.0, 12),
    ]
    for i, (metric, avg, p95, cnt) in enumerate(rows):
        c.execute(
            "INSERT INTO metric_hourly (metric, hour, avg, p95, count) "
            "VALUES (?, ?, ?, ?, ?)",
            (metric, base + i * 3600, avg, p95, cnt),
        )
    c.commit()
    c.close()
    body = client.get(
        "/api/model", params={"from": NOW - 25 * 3600, "to": NOW}
    ).json()
    kpi = body["kpi"]
    assert kpi["prompt_rate"] == pytest.approx(15.0)
    assert kpi["gen_rate"] == pytest.approx(30.0)
    assert kpi["ttft_p50"] == pytest.approx(0.3)
    assert kpi["ttft_p95"] == pytest.approx(0.7)
    assert kpi["e2e_p95"] == pytest.approx(2.0)


def test_model_counter_restart(client, db_path):
    # отрицательный дельта (рестарт vLLM) — не даёт отрицательных значений
    v = "vllm"
    seed_samples(db_path, [
        ("request_success_total_stop", 1500, 100.0, v, None, M_A),
        ("request_success_total_stop", 2500, 30.0, v, None, M_A),  # рестарт
        ("num_preemptions_total", 1500, 9.0, v, None, M_A),
        ("num_preemptions_total", 2500, 1.0, v, None, M_A),
    ])
    body = client.get("/api/model", params={"from": P0, "to": P1}).json()
    kpi = body["kpi"]
    assert kpi["finish_reasons"] == {}
    assert kpi["requests_finished"] is None
    assert kpi["preemptions"] is None
