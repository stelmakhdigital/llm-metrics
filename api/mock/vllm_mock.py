#!/usr/bin/env python3
"""Dev-мок vLLM-сервера (roadmap 0.8, ТЗ §10).

Эмулирует реальный vLLM V1: ``/metrics`` (Prometheus text format, набор
метрик как в ``docs/vllm-metrics-sample.txt``) и ``/v1/models``.
Только stdlib. Запуск: ``make mock-vllm`` или
``python api/mock/vllm_mock.py --port 8000``.

Поведение: гейджи — random walk, счётчики монотонно растут, histogram'ы
накапливаются (каждый «завершённый запрос» добавляет латентности в бакеты).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MODEL = "qwen3.8-27b-dflash2"
ENGINE = 'engine="0"'


class Buckets:
    """Cumulative histogram-бакеты (как в Prometheus)."""

    def __init__(self, edges: list[float | None], rng: random.Random):
        # edges: конечные границы, None = +Inf (последний)
        self.edges = edges
        self.counts = [0.0] * len(edges)
        self.sum = 0.0
        self.n = 0
        self._rng = rng

    def observe(self, x: float) -> None:
        self.sum += x
        self.n += 1
        for i, e in enumerate(self.edges):
            if e is None or x <= e:
                self.counts[i] += 1
                break

    def lines(self, name: str, extra_labels: str = "") -> list[str]:
        lab = f'{ENGINE}{("," + extra_labels) if extra_labels else ""}'
        out = [f"# HELP {name} mock histogram", f"# TYPE {name} histogram"]
        for i, e in enumerate(self.edges):
            le = "+Inf" if e is None else repr(e)
            out.append(f'{name}_bucket{{{lab},le="{le}"}} {self.counts[i]}')
        out.append(f"{name}_count{{{lab}}} {self.n}")
        out.append(f"{name}_sum{{{lab}}} {self.sum:.6f}")
        return out


class MockVllm:
    def __init__(self, model: str, seed: int | None = None):
        self.model = model
        self.rng = random.Random(seed)
        self.started = time.time()
        # счётчики
        self.prompt_tokens = 100_000.0
        self.gen_tokens = 200_000.0
        self.prefix_queries = 50_000.0
        self.prefix_hits = 35_000.0
        self.preemptions = 3.0
        self.finish: dict[str, float] = {"stop": 2900.0, "length": 45.0, "abort": 2.0}
        # гейджи
        self.running = 3
        self.waiting = 1
        self.kv_usage = 0.62
        self._http_2xx = 2974.0
        # histogram'ы
        mlbl = f'model_name="{model}"'
        self.ttft = Buckets([0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, None], self.rng)
        self.tpot = Buckets([0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, None], self.rng)
        self.itl = Buckets([0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, None], self.rng)
        self.e2e = Buckets([0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, None], self.rng)
        self.queue = Buckets([0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, None], self.rng)
        # прогрев: исторические точки
        for _ in range(600):
            self._step_requests()
        self._mlbl = mlbl

    # ------------------------------------------------------------------ step
    def _step_requests(self) -> None:
        """Симулируем 0–3 завершённых запроса за тик."""
        for _ in range(self.rng.randint(0, 3)):
            ttft = min(30.0, self.rng.expovariate(8.0))
            itl = min(2.0, self.rng.expovariate(120.0))
            n_out = self.rng.randint(30, 4000)
            e2e = ttft + n_out * itl
            queue = min(10.0, self.rng.expovariate(50.0))
            tpot = (e2e - ttft) / max(1, n_out)
            self.ttft.observe(ttft)
            self.itl.observe(itl)
            self.e2e.observe(e2e)
            self.queue.observe(queue)
            for _ in range(min(n_out, 40)):
                self.tpot.observe(tpot)
            n_prompt = self.rng.randint(100, 8000)
            self.prompt_tokens += n_prompt
            self.gen_tokens += n_out
            self.prefix_queries += 1
            if self.rng.random() < 0.55:
                self.prefix_hits += 1
            r = self.rng.random()
            key = "stop" if r < 0.93 else ("length" if r < 0.99 else "abort")
            self.finish[key] += 1

    def tick(self) -> None:
        """Один тик (раз в ~1 с): random walk гейджей + рост счётчиков."""
        if self.running > 0:
            self.prompt_tokens += self.rng.uniform(200, 3000)
            self.gen_tokens += self.rng.uniform(500, 8000)
            if self.rng.random() < 0.3:
                self.prefix_queries += self.rng.uniform(1, 20)
                self.prefix_hits += self.rng.uniform(0.5, 12)
        if self.rng.random() < 0.002:
            self.preemptions += 1
        self.running = max(0, min(16, self.running + self.rng.choice([-1, 0, 0, 1])))
        self.waiting = max(0, min(8, self.waiting + self.rng.choice([-1, 0, 1])))
        self.kv_usage = max(0.05, min(0.99, self.kv_usage + self.rng.gauss(0, 0.02)))
        self._http_2xx += 1
        self._step_requests()

    # ------------------------------------------------------------------ text
    def metrics_text(self) -> str:
        m = self._mlbl
        lab = f'{ENGINE},{m}'
        L: list[str] = []
        L.append("# HELP python_info Python process information")
        L.append("# TYPE python_info gauge")
        L.append(f'python_info{{implementation="CPython",major="3",minor="12",patchlevel="14"}} 1.0')
        L.append("# HELP vllm:num_requests_running Mock: Number of requests currently running.")
        L.append("# TYPE vllm:num_requests_running gauge")
        L.append(f"vllm:num_requests_running{{{lab}}} {self.running}")
        L.append("# HELP vllm:num_requests_waiting Mock: Number of requests in waiting queue.")
        L.append("# TYPE vllm:num_requests_waiting gauge")
        L.append(f"vllm:num_requests_waiting{{{lab}}} {self.waiting}")
        L.append("# HELP vllm:kv_cache_usage_perc Mock: KV cache usage by the engine, in [0, 1].")
        L.append("# TYPE vllm:kv_cache_usage_perc gauge")
        L.append(f"vllm:kv_cache_usage_perc{{{lab}}} {self.kv_usage:.4f}")
        L.append("# HELP vllm:engine_sleep_state Mock: Engine sleep state (0=awake).")
        L.append("# TYPE vllm:engine_sleep_state gauge")
        L.append(f"vllm:engine_sleep_state{{{lab}}} 0.0")
        L.append("# HELP vllm:prompt_tokens_total Mock: Prompt tokens.")
        L.append("# TYPE vllm:prompt_tokens_total counter")
        L.append(f"vllm:prompt_tokens_total{{{lab}}} {self.prompt_tokens:.1f}")
        L.append("# HELP vllm:generation_tokens_total Mock: Generation tokens.")
        L.append("# TYPE vllm:generation_tokens_total counter")
        L.append(f"vllm:generation_tokens_total{{{lab}}} {self.gen_tokens:.1f}")
        L.append("# HELP vllm:prefix_cache_queries_total Mock: Prefix cache queries.")
        L.append("# TYPE vllm:prefix_cache_queries_total counter")
        L.append(f"vllm:prefix_cache_queries_total{{{lab}}} {self.prefix_queries:.1f}")
        L.append("# HELP vllm:prefix_cache_hits_total Mock: Prefix cache hits.")
        L.append("# TYPE vllm:prefix_cache_hits_total counter")
        L.append(f"vllm:prefix_cache_hits_total{{{lab}}} {self.prefix_hits:.1f}")
        L.append("# HELP vllm:num_preemptions_total Mock: Preemptions.")
        L.append("# TYPE vllm:num_preemptions_total counter")
        L.append(f"vllm:num_preemptions_total{{{lab}}} {self.preemptions}")
        L.append("# HELP vllm:request_success_total Mock: Successful requests by finished_reason.")
        L.append("# TYPE vllm:request_success_total counter")
        for reason, v in self.finish.items():
            L.append(f'vllm:request_success_total{{{lab},finished_reason="{reason}"}} {v}')
        for name, b in (
            ("vllm:time_to_first_token_seconds", self.ttft),
            ("vllm:request_time_per_output_token_seconds", self.tpot),
            ("vllm:inter_token_latency_seconds", self.itl),
            ("vllm:e2e_request_latency_seconds", self.e2e),
            ("vllm:request_queue_time_seconds", self.queue),
        ):
            L.extend(b.lines(name, m))
        L.append("# HELP vllm:cache_config_info Mock: LLMEngine CacheConfig info.")
        L.append("# TYPE vllm:cache_config_info gauge")
        L.append(
            f'vllm:cache_config_info{{block_size="16",cache_dtype="auto",enable_prefix_caching="True",'
            f'{ENGINE},gpu_memory_utilization="0.9",num_gpu_blocks="1956",{m}}} 1.0'
        )
        L.append("# HELP http_requests_total Total number of requests.")
        L.append("# TYPE http_requests_total counter")
        L.append(f'http_requests_total{{handler="/v1/chat/completions",method="POST",status="2xx"}} {self._http_2xx}')
        L.append("http_requests_total{handler=\"/v1/models\",method=\"GET\",status=\"2xx\"} 3.0")
        return "\n".join(L) + "\n"

    def models_json(self) -> str:
        return json.dumps(
            {
                "object": "list",
                "data": [
                    {
                        "id": self.model,
                        "object": "model",
                        "created": int(self.started),
                        "owned_by": "vllm",
                        "max_model_len": 262144,
                    }
                ],
            }
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "vllm-mock/0.1"
    mock: MockVllm  # типизация для линтеров

    def log_message(self, fmt: str, *args) -> None:  # тише
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/metrics":
            body = self.mock.metrics_text().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/v1/models":
            body = self.mock.models_json().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def main() -> None:
    ap = argparse.ArgumentParser(description="mock vLLM server (dev)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    mock = MockVllm(model=args.model, seed=args.seed)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    Handler.mock = mock

    def tiker() -> None:
        while True:
            time.sleep(1.0)
            try:
                mock.tick()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=tiker, daemon=True).start()
    print(f"mock vLLM: http://{args.host}:{args.port} (model={args.model})", flush=True)
    print("  GET /metrics, /v1/models; Ctrl-C — стоп", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
