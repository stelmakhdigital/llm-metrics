"""Автопарсинг stat-строк инференса в боковую колонку (ТЗ §5.6).

Обычная stat-строка vLLM:
``Engine00: Running: 3 reqs, Waiting: 2 reqs, GPU KV cache usage: 12.3%,
Prefix cache hit rate: 4.5%``; throughput-строки:
``Avg prompt throughput: 45.1 toks/s`` и т.п.

Stat-строки Project Maya (движок strata; running/waiting в логе нет):
``glm stat: decode 22.54 ms/tok (44.36 tok/s) | vram hit 99.77% | …
vram 12218/12513 ram 5/308``; итог запроса:
``[maya] done: 1349 tokens in 35 s (49.4 tok/s) (stop, …), expert cache
99.9% hit``; фазы: ``[maya] thinking: 1177 of max 16384 tokens, 48.6 tok/s, 32 s``.

Маппинг maya: tok/s → avg_generation_throughput, ``vram X/Y`` (занятость
экспертного кэша) → kv_cache_pct (тот же аналог KV, что и в коллекторе).
«expert cache N% hit» — НЕ prefix-кэш, не маппим.
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

# maya: скорость генерации — «(44.36 tok/s)» / «48.6 tok/s» («toks/s» vLLM
# не матчится — там без слэша)
_MAYA_TOKS = re.compile(r"([0-9.]+)\s*tok/s")
# maya: занятость экспертного кэша «vram 12218/12513» (не «vram hit …»,
# не «ram X/Y»)
_MAYA_VRAM = re.compile(r"(?<!\w)vram\s+(\d+)\s*/\s*(\d+)")


def parse_stat(line: str) -> dict[str, Any] | None:
    """Набор stat-полей строки (vLLM/maya); None, если ничего не найдено."""
    out: dict[str, Any] = {}
    for key, pat in STAT_PATTERNS.items():
        m = pat.search(line)
        if not m:
            continue
        raw = m[1]
        out[key] = int(raw) if re.fullmatch(r"\d+", raw) else float(raw)
    m = _MAYA_TOKS.search(line)
    if m and "avg_generation_throughput" not in out:
        out["avg_generation_throughput"] = float(m[1])
    m = _MAYA_VRAM.search(line)
    if m and "kv_cache_pct" not in out:
        used, total = int(m[1]), int(m[2])
        if total > 0:
            out["kv_cache_pct"] = round(100.0 * used / total, 2)
    return out or None


# Старое имя (до поддержки maya) — для обратной совместимости.
parse_vllm_stat = parse_stat
