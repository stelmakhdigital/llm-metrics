"""Парсер Prometheus text exposition format (без prometheus_client).

Парсит ``# HELP``/``# TYPE`` и строки образцов ``name{label="v"} value``.
Метрики возвращаются как словарь ``имя -> Metric`` (тип + серии с лейблами).
Histogram'ы приходят отдельными именами: ``x_bucket`` (лейбл ``le``),
``x_count``, ``x_sum`` — маппинг делает :mod:`app.collectors.vllm`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Metric", "Series", "parse_prometheus"]

_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')
_HELP_RE = re.compile(r"^# HELP\s+(\S+)\s*(.*)$")
_TYPE_RE = re.compile(r"^# TYPE\s+(\S+)\s+(\S+)")
_VALUE_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

# Сентинел «не значение» (отличается от None — законного NaN)
_INVALID = object()


@dataclass
class Series:
    labels: dict[str, str]
    value: float | None  # NaN/+Inf приходят из vLLM как None-безопасные float


@dataclass
class Metric:
    type: str | None = None  # gauge | counter | histogram | summary | untyped
    series: list[Series] = field(default_factory=list)


def _parse_labels(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _LABEL_RE.finditer(s):
        key, val = m.group(1), m.group(2)
        # Экранирование в значениях: \" \\ \n
        out[key] = (
            val.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        )
    return out


def _to_float(s: str) -> float | None | object:
    """float значения; None для NaN; _INVALID для не-числа."""
    s = s.strip()
    if s == "NaN":
        return None
    if s == "+Inf":
        return float("inf")
    if s == "-Inf":
        return float("-inf")
    if _VALUE_RE.match(s):
        return float(s)
    return _INVALID


def parse_prometheus(text: str) -> dict[str, Metric]:
    """Разбирает текст Prometheus на метрики.

    Мелкие недочёты входного текста (пустые строки, комментарии без
    HELP/TYPE, битые значения) пропускаются, а не роняют парсинг.
    """
    out: dict[str, Metric] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# HELP"):
            m = _HELP_RE.match(line)
            if m:
                out.setdefault(m.group(1), Metric())
            continue
        if line.startswith("# TYPE"):
            m = _TYPE_RE.match(line)
            if m:
                met = out.setdefault(m.group(1), Metric())
                met.type = m.group(2)
            continue
        if line.startswith("#"):
            continue

        # Строка образца: name{labels} value [timestamp]
        brace = line.find("{")
        if brace != -1:
            end = line.find("}", brace)
            if end == -1:
                continue
            name = line[:brace]
            labels = _parse_labels(line[brace + 1 : end])
            rest = line[end + 1 :].split()
        else:
            parts = line.split()
            if len(parts) < 2:
                continue
            name, labels, rest = parts[0], {}, parts[1:]
        if not name:
            continue
        value = _to_float(rest[0]) if rest else _INVALID
        if value is _INVALID:
            continue  # битая строка образца — пропускаем
        met = out.setdefault(name, Metric())
        met.series.append(Series(labels=labels, value=value))
    return out
