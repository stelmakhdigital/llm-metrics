"""Квантили по cumulative buckets Prometheus-histogram.

Метод зафиксирован в ТЗ §5.2: **p95 считается интерполяцией по buckets**
(линейная интерполяция внутри bucket'а, в который попадает целевая доля;
нижняя граница первого bucket'а — 0). Аппроксимация, достаточная для
операционного мониторинга.
"""

from __future__ import annotations

import math

__all__ = ["percentile_from_buckets", "percentiles_from_buckets"]


def percentile_from_buckets(
    buckets: list[tuple[float, float]], p: float
) -> float | None:
    """K-quantile по cumulative buckets.

    :param buckets: пары ``(le, cumulative_count)``, ``le`` может быть ``inf``
        (bucket ``+Inf`` — последний). Порядок не обязателен — сортируется.
    :param p: доля в [0, 1].
    :returns: значение или ``None`` (нет данных / пустые buckets).
    """
    if not (0.0 <= p <= 1.0) or not buckets:
        return None
    ordered = sorted(
        buckets, key=lambda b: (math.isinf(b[0]) and b[0] > 0, b[0])
    )
    total = ordered[-1][1]
    if total is None or total <= 0:
        return None
    target = p * total
    prev_le, prev_c = 0.0, 0.0
    for le, c in ordered:
        if c is None:
            continue
        if c >= target:
            if c == prev_c:
                # Целевая доля попала в пустой bucket — возвращаем нижнюю
                # границу следующего непустого участка (консервативная оценка)
                return prev_le
            frac = (target - prev_c) / (c - prev_c)
            if math.isinf(le):
                # Выше последнего конечного bucket'а данных нет —
                # отдаём границу последнего конечного bucket'а
                return prev_le
            return prev_le + (le - prev_le) * frac
        prev_le, prev_c = le, c
    return None


def percentiles_from_buckets(
    buckets: list[tuple[float, float]], ps: tuple[float, ...]
) -> dict[float, float | None]:
    """Несколько квантилей одним проходом (дешёво: O(k·n))."""
    return {p: percentile_from_buckets(buckets, p) for p in ps}
