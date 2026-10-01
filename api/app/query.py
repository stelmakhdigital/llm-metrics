"""Даунсемплинг рядов для графиков (ТЗ §8.3: ≤1500 точек за 30 дней)."""

from __future__ import annotations

import math

__all__ = ["MAX_POINTS", "downsample"]

# Цель — ~200 точек: как у hourly-агрегата на 7 дней (168 точек) —
# графики на 1ч/24ч выглядят как на длинных периодах, точки не слипаются.
MAX_POINTS = 200


def downsample(points: list[list[float]], max_points: int = MAX_POINTS) -> list[list[float]]:
    """Среднее по временным бакетам: одна точка на бакет.

    * Бакеты — по времени (привязка к сетке epoch, не по индексам) —
      неровная дискретизация не искажается;
    * ts точки — середина бакета (конвенция как у hourly: ``hour + 1800``);
    * Пустые бакеты (разрывы в данных) пропускаются — разрыв остаётся разрывом;
    * результат ≤ max_points точек, порядок времени не нарушается.
    """
    n = len(points)
    if n <= max_points:
        return points
    span = int(points[-1][0] - points[0][0])
    # (span // size) + 1 ≤ max_points: ширина с запасом на крайний бакет
    size = max(1, math.ceil(span / (max_points - 1))) if max_points > 1 else 1
    # бакет → [count, sum]; order — порядок появления (ts сортированы)
    acc: dict[int, list[float]] = {}
    order: list[int] = []
    for ts, v in points:
        b = int(ts) // size
        a = acc.get(b)
        if a is None:
            acc[b] = [1.0, float(v)]
            order.append(b)
        else:
            a[0] += 1
            a[1] += float(v)
    out: list[list[float]] = []
    for b in order:
        c, s = acc[b]
        out.append([b * size + size / 2, s / c])
    return out
