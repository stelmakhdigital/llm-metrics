"""Тесты логического маппинга метрик vLLM (на реальном сэмпле
docs/vllm-metrics-sample.txt + синтетический текст для rates/рестарта)."""

import re
from pathlib import Path

import httpx
import pytest

from app.collectors.vllm import VllmCollector, VllmError
from app.config import VllmSource
from conftest import REPO_ROOT

SAMPLE_FILE = REPO_ROOT / "docs" / "vllm-metrics-sample.txt"


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
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status = status

    async def get(self, url, timeout=None):
        return FakeResp(self.text, self.status)


def by_metric(samples):
    return {s.metric: s for s in samples}


def test_real_sample_mapping():
    import asyncio

    text = SAMPLE_FILE.read_text(encoding="utf-8")
    col = VllmCollector(VllmSource())
    ts = 1_700_000_000
    samples = asyncio.run(col.poll(FakeClient(text), now=ts))
    m = by_metric(samples)

    # значения из docs/vllm-metrics-sample.txt (снимок 2026-07-25)
    assert m["num_requests_running"].value == 1.0
    assert m["num_requests_waiting"].value == 0.0
    # kv_cache_usage_perc 0..1 → 0..100
    assert m["kv_cache_usage"].value == pytest.approx(9.71867, abs=1e-3)
    # модель из лейблов
    assert all(s.model == "qwen3.8-27b-dflash2" for s in samples if s.model)

    # сырые счётчики (для токенизатора)
    assert m["prompt_tokens_total"].value == pytest.approx(2.83278093e8, abs=1.0)
    assert m["generation_tokens_total"].value == pytest.approx(2.298968e6, abs=1.0)

    # finish reasons — сырые счётчики с суффиксом {reason}
    assert m["request_success_total_stop"].value == 2946.0
    assert m["request_success_total_length"].value == 2.0
    assert m["request_success_total_abort"].value == 0.0

    # p95 TTFT: интерполяция в bucket [7.5, 10): 0.95*2962 = 2813.9
    # → 7.5 + 2.5 * (2813.9-2801)/(2839-2801) ≈ 8.3487
    assert m["ttft_p95"].value == pytest.approx(8.3487, abs=1e-3)
    # p50 TTFT: bucket [1.0, 2.5): 1.0 + 1.5 * (1481-891)/(1786-891) ≈ 1.9888
    assert m["ttft_p50"].value == pytest.approx(1.9888, abs=1e-3)
    assert m["e2e_latency_p95"].value is not None
    assert m["tpot_p95"].value is not None
    assert m["queue_time_p95"].value is not None

    # первый poll: rates ещё нет (нет базового замера)
    assert "prompt_tokens_rate" not in m
    assert "generation_tokens_rate" not in m


def _small_text(prompt: float, gen: float) -> str:
    return (
        "# TYPE vllm:prompt_tokens_total counter\n"
        f'vllm:prompt_tokens_total{{engine="0",model_name="m1"}} {prompt:.1f}\n'
        "# TYPE vllm:generation_tokens_total counter\n"
        f'vllm:generation_tokens_total{{engine="0",model_name="m1"}} {gen:.1f}\n'
    )


def test_counter_rates_and_restart_guard():
    import asyncio

    async def run():
        col = VllmCollector(VllmSource())
        s1 = await col.poll(FakeClient(_small_text(1000.0, 500.0)), now=1000)
        s2 = await col.poll(FakeClient(_small_text(2000.0, 700.0)), now=1005)
        m2 = by_metric(s2)
        # 5 с дельты 1000 / 200
        assert m2["prompt_tokens_rate"].value == pytest.approx(200.0)
        assert m2["generation_tokens_rate"].value == pytest.approx(40.0)
        # рестарт: счётчик упал → rate не считается, флаг _restart
        s3 = await col.poll(FakeClient(_small_text(50.0, 700.0)), now=1010)
        m3 = by_metric(s3)
        assert "prompt_tokens_rate" not in m3
        assert m3["prompt_tokens_total_restart"].value == 1.0
        # generation не падал → rate считается от нового базового (700→700 → 0)
        assert m3["generation_tokens_rate"].value == pytest.approx(0.0)
        return m3

    m3 = asyncio.run(run())
    assert m3["generation_tokens_total"].value == 700.0


def test_source_unavailable():
    import asyncio

    col = VllmCollector(VllmSource())
    with pytest.raises(VllmError):
        asyncio.run(col.poll(FakeClient("", status=500), now=1000))


def test_model_fallback_to_config():
    import asyncio

    text = "# TYPE vllm:num_requests_running gauge\nvllm:num_requests_running 1\n"
    col = VllmCollector(VllmSource(model_name="configured-model"))
    samples = asyncio.run(col.poll(FakeClient(text), now=1000))
    assert samples[0].model == "configured-model"


def test_token_bucket_counters_stored():
    """Кумулятивные счётчики bucket'ов длин prompt/generation (F1):
    ``request_prompt_tokens_bucket_{le}`` / ``request_generation_tokens_bucket_{le}``,
    le — числовое, +Inf не хранится; несколько engine — сумма."""
    import asyncio

    text = (
        'vllm:num_requests_running{model_name="m"} 2.0\n'
        'vllm:request_prompt_tokens_bucket{engine="0",le="16.0",model_name="m"} 100.0\n'
        'vllm:request_prompt_tokens_bucket{engine="0",le="32.0",model_name="m"} 400.0\n'
        'vllm:request_prompt_tokens_bucket{engine="1",le="16.0",model_name="m"} 50.0\n'
        'vllm:request_prompt_tokens_bucket{engine="0",le="+Inf",model_name="m"} 1000.0\n'
        'vllm:request_generation_tokens_bucket{engine="0",le="8",model_name="m"} 7.0\n'
    )
    col = VllmCollector(VllmSource())
    samples = asyncio.run(col.poll(FakeClient(text), now=1_700_000_000))
    m = by_metric(samples)
    assert m["request_prompt_tokens_bucket_16"].value == 150.0  # сумма по engine
    assert m["request_prompt_tokens_bucket_32"].value == 400.0
    assert m["request_generation_tokens_bucket_8"].value == 7.0
    assert not any("Inf" in s.metric for s in samples)
    assert m["request_prompt_tokens_bucket_16"].model == "m"

    # кэш последнего снимка (F1)
    snap = col.last_snapshot
    assert snap["model"] == "m"
    assert snap["ts"] == 1_700_000_000
    assert snap["metrics"]["num_requests_running"] == 2.0
    # сырые bucket-счётчики в снимок не попадают
    assert "request_prompt_tokens_bucket_16" not in snap["metrics"]
