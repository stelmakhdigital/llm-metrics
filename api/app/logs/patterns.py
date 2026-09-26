"""Автопарсинг stat-строк vLLM в боковую колонку (ТЗ §5.6).

Обычная stat-строка vLLM:
``Engine00: Running: 3 reqs, Waiting: 2 reqs, GPU KV cache usage: 12.3%,
Prefix cache hit rate: 4.5%``; throughput-строки:
``Avg prompt throughput: 45.1 toks/s`` и т.п.
"""

from __future__ import annotations

import re
from typing import Any

# ключ → regex; значения — числовые
STAT_PATTERNS: dict[str, re.Pattern] = {
    "running": re.compile(r"Running:\s*(\d+)\s*reqs", re.IGNORECASE),
    "waiting": re.compile(r"Waiting:\s*(\d+)\s*reqs", re.IGNORECASE),
    "kv_cache_pct": re.compile(r"GPU KV cache usage:\s*([0-9.]+)\s*%", re.IGNORECASE),
    "avg_prompt_throughput": re.compile(
        r"Avg prompt throughput:\s*([0-9.]+)", re.IGNORECASE
    ),
    "avg_generation_throughput": re.compile(
        r"Avg generation throughput:\s*([0-9.]+)", re.IGNORECASE
    ),
    "prefix_cache_hit_rate_pct": re.compile(
        r"Prefix cache hit rate:\s*([0-9.]+)\s*%", re.IGNORECASE
    ),
}


def parse_vllm_stat(line: str) -> dict[str, Any] | None:
    """Набор stat-полей строки; None, если ни один паттерн не найден."""
    out: dict[str, Any] = {}
    for key, pat in STAT_PATTERNS.items():
        m = pat.search(line)
        if not m:
            continue
        raw = m[1]
        out[key] = int(raw) if re.fullmatch(r"\d+", raw) else float(raw)
    return out or None
