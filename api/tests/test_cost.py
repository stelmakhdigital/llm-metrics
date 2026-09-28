"""Тесты cost engine + тарифов (F2): ручная сверка формул ТЗ §6 (критерий ±1%)."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import seed_samples

# Чистый час UTC (1756200000 ≈ 2025-08-26).
T = (1756200000 // 3600) * 3600
APPROX = dict(rel=0.01)  # критерий ТЗ: ±1%


@pytest.fixture
def client(make_app, db_path):
    app = make_app()
    with TestClient(app) as c:
        yield c


def _settings(db_path, versions):
    c = sqlite3.connect(str(db_path))
    c.execute(
        "UPDATE settings SET value = ? WHERE key = 'cost_rates'",
        (json.dumps(versions),),
    )
    c.commit()
    c.close()


def _rate(ts, **kw):
    v = {
        "currency": "USD",
        "rate_per_kwh_usd": 0.10,
        "system_baseline_watts": 200,
        "token_prompt_per_million_usd": 0.5,
        "token_completion_per_million_usd": 1.5,
    }
    v.update(kw)
    v["updated_at"] = ts
    return v


# ------------------------------------------------------------------ электричество


def test_electricity_raw_1h(client, db_path):
    """300W + baseline 200W за 1ч → P=500W → kWh = 0.5 (ТЗ §6), elec = 0.5 * 0.10 $."""
    seed_samples(
        db_path,
        [("gpu_power", T + 300 * i, 300.0, "gpu", 0, None) for i in range(13)],
    )
    r = client.get("/api/cost", params={"from": T, "to": T + 3600})
    assert r.status_code == 200
    body = r.json()
    assert body["kwh"] == pytest.approx(0.5, **APPROX)
    assert body["elec_cost"] == pytest.approx(0.5 * 0.10, **APPROX)
    assert body["tokens_cost"] == pytest.approx(0.0)
    assert body["total"] == pytest.approx(0.05, **APPROX)
    assert body["avg_power_w"] == pytest.approx(500.0, **APPROX)
    assert len(body["by_day"]) == 1
    assert body["by_day"][0]["day"] == (T // 86400) * 86400
    assert body["by_day"][0]["kwh"] == pytest.approx(0.5, **APPROX)


def test_electricity_multigpu_sum(client, db_path):
    """ТЗ §6: P_total = Σ_gpu P_gpu + baseline — 300W (gpu 0) + 200W (gpu 1)
    + 200W baseline = 700W за 1ч → 0.7 kWh."""
    seed_samples(
        db_path,
        [
            ("gpu_power", T, 300.0, "gpu", 0, None),
            ("gpu_power", T + 3600, 300.0, "gpu", 0, None),
            ("gpu_power", T, 200.0, "gpu", 1, None),
            ("gpu_power", T + 3600, 200.0, "gpu", 1, None),
        ],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    assert body["kwh"] == pytest.approx(0.7, **APPROX)
    assert body["elec_cost"] == pytest.approx(0.7 * 0.10, **APPROX)
    assert body["avg_power_w"] == pytest.approx(700.0, **APPROX)


def test_electricity_gap_hours_not_zero(client, db_path):
    """Данные только за 1-й час из 2 → второй час не засчитывается (разрыв)."""
    seed_samples(
        db_path,
        [("gpu_power", T + 300 * i, 300.0, "gpu", 0, None) for i in range(13)],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 7200}).json()
    assert body["kwh"] == pytest.approx(0.5, **APPROX)
    assert len(body["cumulative"]) == 1
    assert body["cumulative"][0][0] == T + 3600


def test_electricity_hourly_fallback(client, db_path):
    """Час без сырых выборок — из metric_hourly (avg=300W) + tokens-строка."""
    c = sqlite3.connect(str(db_path))
    c.execute(
        "INSERT INTO metric_hourly (metric, hour, avg, min, max, p95, count) "
        "VALUES ('gpu_power', ?, 300.0, 300.0, 300.0, 300.0, 12)",
        (T,),
    )
    c.execute(
        "INSERT INTO tokens (ts, prompt_tokens, completion_tokens, requests_finished) "
        "VALUES (?, 1000000, 1000000, 10)",
        (T,),
    )
    c.commit()
    c.close()
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    assert body["kwh"] == pytest.approx(0.5, **APPROX)
    assert body["elec_cost"] == pytest.approx(0.5 * 0.10, **APPROX)
    assert body["tokens_cost"] == pytest.approx(0.5 + 1.5, **APPROX)
    assert body["requests"] == 10
    assert body["avg_power_w"] == pytest.approx(500.0, **APPROX)


def test_electricity_hourly_fallback_multigpu(client, db_path):
    """hourly-fallback с per-gpu строками: Σ avg по gpu (300+200) + 200W baseline = 700W."""
    c = sqlite3.connect(str(db_path))
    for gpu in (0, 1):
        c.execute(
            "INSERT INTO metric_hourly (metric, hour, gpu, avg, min, max, p95, count) "
            "VALUES ('gpu_power', ?, ?, ?, ?, ?, ?, ?)",
            (T, gpu, 300.0 if gpu == 0 else 200.0,
             300.0 if gpu == 0 else 200.0,
             300.0 if gpu == 0 else 200.0,
             300.0 if gpu == 0 else 200.0, 12),
        )
    c.commit()
    c.close()
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    assert body["kwh"] == pytest.approx(0.7, **APPROX)
    assert body["avg_power_w"] == pytest.approx(700.0, **APPROX)


# ----------------------------------------------------------------------- токены


def test_tokens_raw_1m(client, db_path):
    """1M prompt + 1M completion → tokens_cost = 0.5 + 1.5 $ (тарифы из конфига)."""
    seed_samples(
        db_path,
        [
            ("prompt_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("prompt_tokens_total", T + 3600, 1_000_000.0, "vllm", None, "m1"),
            ("generation_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("generation_tokens_total", T + 3600, 1_000_000.0, "vllm", None, "m1"),
            ("request_success_total_stop", T, 0.0, "vllm", None, "m1"),
            ("request_success_total_stop", T + 3600, 42.0, "vllm", None, "m1"),
        ],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    assert body["tokens_cost"] == pytest.approx(0.5 + 1.5, **APPROX)
    assert body["prompt_tokens"] == 1_000_000
    assert body["completion_tokens"] == 1_000_000
    assert body["requests"] == 42
    assert body["elec_cost"] == pytest.approx(0.0)
    assert body["per_request"] == pytest.approx(2.0 / 42, **APPROX)
    assert body["per_1k_out_tok"] == pytest.approx(2.0 * 1000 / 1_000_000, **APPROX)


def test_zero_completion_null_unit_costs(client, db_path):
    """completion = 0 → per_1k_out_tok = null; requests = 0 → per_request = null."""
    seed_samples(
        db_path,
        [
            ("prompt_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("prompt_tokens_total", T + 3600, 1_000_000.0, "vllm", None, "m1"),
            ("generation_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("generation_tokens_total", T + 3600, 0.0, "vllm", None, "m1"),
        ],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    assert body["tokens_cost"] == pytest.approx(0.5, **APPROX)
    assert body["completion_tokens"] == 0
    assert body["per_1k_out_tok"] is None
    assert body["per_request"] is None


# --------------------------------------------------------------- версионирование


def test_rate_versioning_mid_period(client, db_path):
    """Ставка prompt меняется посередине периода → разные суммы за каждый час."""
    _settings(db_path, [_rate(T, token_prompt_per_million_usd=0.5),
                        _rate(T + 1800, token_prompt_per_million_usd=1.0)])
    seed_samples(
        db_path,
        [
            ("prompt_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("prompt_tokens_total", T + 3600, 1_000_000.0, "vllm", None, "m1"),
            ("prompt_tokens_total", T + 7200, 2_000_000.0, "vllm", None, "m1"),
            ("generation_tokens_total", T, 0.0, "vllm", None, "m1"),
            ("generation_tokens_total", T + 3600, 0.0, "vllm", None, "m1"),
            ("generation_tokens_total", T + 7200, 0.0, "vllm", None, "m1"),
        ],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 7200}).json()
    # 1-й час — ставка 0.5 $/1M, 2-й (смена после T+1800) — 1.0 $/1M
    assert body["tokens_cost"] == pytest.approx(0.5 + 1.0, **APPROX)
    assert body["prompt_tokens"] == 2_000_000
    assert body["per_1k_out_tok"] is None


# ----------------------------------------------------------------- GET /api/cost


def test_cost_default_today(client):
    """Без from/to — «сегодня» (00:00 UTC → now)."""
    r = client.get("/api/cost")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "USD"
    for key in (
        "total", "tokens_cost", "elec_cost", "kwh", "avg_power_w",
        "per_1k_out_tok", "per_request", "requests",
        "prompt_tokens", "completion_tokens",
        "by_day", "cumulative", "power_by_day",
    ):
        assert key in body
    assert body["total"] == 0.0


def test_cost_invalid_range(client):
    assert client.get("/api/cost", params={"from": T + 100, "to": T}).status_code == 400


# ------------------------------------------------------------- /api/settings/cost


def test_settings_cost_get_seed(client):
    """Seed при старте: версия из конфига cost.* (USD, 0.10, 200W, 0.5/1.5)."""
    body = client.get("/api/settings/cost").json()
    cur = body["current"]
    assert cur["currency"] == "USD"
    assert cur["rate_per_kwh_usd"] == pytest.approx(0.10)
    assert cur["system_baseline_watts"] == pytest.approx(200.0)
    assert cur["token_prompt_per_million_usd"] == pytest.approx(0.5)
    assert cur["token_completion_per_million_usd"] == pytest.approx(1.5)
    assert len(body["history"]) == 1
    assert body["history"][0]["updated_at"] == cur["updated_at"]


def test_settings_cost_put_adds_version(client):
    """PUT добавляет версию, не редактирует старые; история растёт."""
    r = client.put("/api/settings/cost", json={"rate_per_kwh_usd": 0.25})
    assert r.status_code == 200
    cur = r.json()["current"]
    assert cur["rate_per_kwh_usd"] == pytest.approx(0.25)
    # остальные поля наследуются от текущей версии
    assert cur["token_prompt_per_million_usd"] == pytest.approx(0.5)
    assert cur["currency"] == "USD"

    body = client.get("/api/settings/cost").json()
    assert len(body["history"]) == 2
    assert body["current"] is not None
    # новые первыми; старая версия не изменилась
    assert body["history"][0]["rate_per_kwh_usd"] == pytest.approx(0.25)
    assert body["history"][1]["rate_per_kwh_usd"] == pytest.approx(0.10)
    assert body["history"][1] != body["history"][0]


def test_settings_cost_put_validation(client):
    assert client.put("/api/settings/cost", json={}).status_code == 400
    assert client.put("/api/settings/cost", json={"rate_per_kwh_usd": -1}).status_code == 422


def test_new_rate_applies_from_next_hour(client, db_path):
    """Тариф, сохранённый PUT-ом, действует для часов после его updated_at."""
    client.put("/api/settings/cost", json={"rate_per_kwh_usd": 10.0})
    seed_samples(
        db_path,
        [("gpu_power", T + 300 * i, 300.0, "gpu", 0, None) for i in range(13)],
    )
    body = client.get("/api/cost", params={"from": T, "to": T + 3600}).json()
    # старая ставка 0.10 $/кВт·ч (версия от конфига старее часа T)
    assert body["elec_cost"] == pytest.approx(0.5 * 0.10, **APPROX)
