"""Коллектор с source_type=maya: маппинг JSON-снимка maya (реальный
docs/maya-metrics-sample.json) + rates/рестарт на синтетике.

Значения в снимке «живые» (сервер maya работает) — все ожидания
относительные: от полей самой фикстуры, не константы.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.collectors.vllm import VllmCollector, VllmError
from app.config import VllmSource
from conftest import REPO_ROOT

SAMPLE_FILE = REPO_ROOT / "docs" / "maya-metrics-sample.json"


class FakeResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self
            )


class FakeClient:
    """Очередь тел ответов (один poll — одно GET)."""

    def __init__(self, *bodies: str):
        self.bodies = list(bodies)
        self.urls: list[str] = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        return FakeResp(self.bodies.pop(0) if self.bodies else "")


def by_metric(samples):
    return {s.metric: s for s in samples}


@pytest.fixture
def sample_text() -> str:
    return SAMPLE_FILE.read_text(encoding="utf-8")


@pytest.fixture
def sample_payload(sample_text):
    return json.loads(sample_text)


def make_collector():
    return VllmCollector(
        VllmSource(url="http://127.0.0.1:8080", source_type="maya")
    )


def test_real_sample_mapping(sample_payload, sample_text):
    col = make_collector()
    samples = asyncio.run(col.poll(FakeClient(sample_text), now=1_700_000_000))
    m = by_metric(samples)

    now = sample_payload["tiers"]["now"]
    assert m["num_requests_running"].value == sample_payload["live"]["active"]
    assert m["num_requests_waiting"].value == sample_payload["live"]["queued"]
    # vram_used/vram_slots → 0..100 %
    assert m["kv_cache_usage"].value == pytest.approx(
        100.0 * now["vram_used"] / now["vram_slots"], abs=1e-6
    )
    assert 0 <= m["kv_cache_usage"].value <= 100
    # сырые счётчики из totals
    totals = sample_payload["totals"]
    assert m["prompt_tokens_total"].value == totals["prompt_tokens"]
    assert m["generation_tokens_total"].value == totals["output_tokens"]
    assert m["prefix_cache_hits_total"].value == totals["reused"]
    # прокси queries = prompt_tokens
    assert m["prefix_cache_queries_total"].value == totals["prompt_tokens"]
    # метка модели из engine.model
    assert all(s.model == sample_payload["engine"]["model"] for s in samples if s.model)
    # источник — по-прежнему 'vllm' (единый пайплайн хранения)
    assert all(s.source == "vllm" for s in samples)


def test_histogram_quantiles_from_requests_window(sample_payload, sample_text):
    col = make_collector()
    samples = asyncio.run(col.poll(FakeClient(sample_text), now=1_700_000_000))
    m = by_metric(samples)

    reqs = sample_payload["requests"]
    assert reqs, "в фикстуре должно быть окно requests"
    ttft = sorted(r["prompt_ms"] / 1000.0 for r in reqs)
    # p50/p95 по окну: интерполяция по buckets (может выходить за max данных
    # — как и у vLLM), но внутри bucket-сеток
    assert ttft[0] <= m["ttft_p50"].value <= ttft[-1]
    assert 0 < m["ttft_p50"].value <= m["ttft_p95"].value < 60
    tpot = sorted(
        r["decode_ms"] / r["output_tokens"] / 1000.0
        for r in reqs
        if r.get("output_tokens")
    )
    assert 0 < m["tpot_p50"].value <= m["tpot_p95"].value <= max(tpot) * 2 + 0.1
    e2e = sorted(r["duration_s"] for r in reqs)
    assert e2e[0] <= m["e2e_latency_p50"].value <= e2e[-1]
    # bucket'ы длин prompt/generation хранятся как request_*_bucket_{le}
    prompts = [float(r["prompt_tokens"]) for r in reqs]
    assert m["request_prompt_tokens_bucket_65536"].value == float(len(prompts))
    outs = [float(r["output_tokens"]) for r in reqs]
    assert m["request_generation_tokens_bucket_16384"].value == float(len(outs))
    assert m["request_generation_tokens_bucket_1"].value == float(
        sum(v <= 1 for v in outs)
    )


def test_two_polls_same_snapshot_rates_zero_and_rolling(sample_text):
    col = make_collector()
    cli = FakeClient(sample_text, sample_text)
    asyncio.run(col.poll(cli, now=1_700_000_000))
    samples = asyncio.run(col.poll(cli, now=1_700_000_065))
    m = by_metric(samples)
    # счётчики не растут (тот же снимок) → rates 0, без _restart
    assert m["prompt_tokens_rate"].value == 0.0
    assert "prompt_tokens_total_restart" not in m
    # rolling-окно ~60 с достуго (шаг 65 с > 60)
    assert m["prompt_tokens_rate_60s"].value == 0.0
    assert m["generation_tokens_rate_60s"].value == 0.0


def test_restart_protection(sample_payload, sample_text):
    col = make_collector()
    # «Рестарт»: все счётчики меньше, чем в первом снимке
    smaller = json.loads(sample_text)
    t = sample_payload["totals"]
    smaller["totals"] = {
        "requests": 1, "prompt_tokens": 100, "reused": 50, "output_tokens": 10,
    }
    cli = FakeClient(sample_text, json.dumps(smaller))
    asyncio.run(col.poll(cli, now=1_700_000_000))
    samples = asyncio.run(col.poll(cli, now=1_700_000_010))
    m = by_metric(samples)
    assert m["prompt_tokens_total_restart"].value == 1.0
    assert "prompt_tokens_rate" not in m


def test_counter_growth_rates(sample_payload, sample_text):
    col = make_collector()
    grown = json.loads(sample_text)
    t = sample_payload["totals"]
    grown["totals"]["prompt_tokens"] = t["prompt_tokens"] + 5000
    grown["totals"]["output_tokens"] = t["output_tokens"] + 1000
    grown["totals"]["reused"] = t["reused"]  # hits не растут
    cli = FakeClient(sample_text, json.dumps(grown))
    asyncio.run(col.poll(cli, now=1_700_000_000))
    samples = asyncio.run(col.poll(cli, now=1_700_000_065))
    m = by_metric(samples)
    assert m["prompt_tokens_rate"].value == pytest.approx(5000 / 65)
    assert m["generation_tokens_rate"].value == pytest.approx(1000 / 65)
    assert m["prompt_tokens_rate_60s"].value == pytest.approx(5000 / 65)
    # prefix hit rate за интервал: dh == 0 → 0.0 (hits/queries)
    assert m["prefix_hit_rate"].value == 0.0


def test_bad_json_raises():
    col = make_collector()
    with pytest.raises(VllmError):
        asyncio.run(col.poll(FakeClient("<html>bad</html>"), now=1_700_000_000))


def test_url_from_config(sample_text):
    col = make_collector()
    cli = FakeClient(sample_text)
    asyncio.run(col.poll(cli, now=1_700_000_000))
    assert cli.urls[-1] == "http://127.0.0.1:8080/metrics"
