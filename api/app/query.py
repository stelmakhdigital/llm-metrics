"""Даунсемплинг рядов для графиков (ТЗ §8.3: ≤1500 точек за 30 дней)."""

from __future__ import annotations

__all__ = ["MAX_POINTS", "downsample"]

MAX_POINTS = 1500


def downsample(points: list[list[float]], max_points: int = MAX_POINTS) -> list[list[float]]:
    """Min-max decimation: из каждого бакета — точка минимума и максимума.

    * Хранит форму всплесков (не «гладит»);
    * результат ≤ max_points точек;
    * первая и последняя точки исходного ряда сохраняются;
    * порядок времени не нарушается.
    """
    n = len(points)
    if n <= max_points:
        return points
    # бакетов = max_points//2 → до 2 точек (ло/хай) на бакет → ≤ ~max_points
    buckets = max(1, max_points // 2)
    size = (n + buckets - 1) // buckets

    def push(out: list, p) -> None:
        if not out or out[-1] is not p:
            out.append(p)

    out: list[list[float]] = [points[0]]
    for i in range(buckets):
        chunk = points[i * size : min(n, (i + 1) * size)]
        if not chunk:
            continue
        lo = min(chunk, key=lambda p: p[1])
        hi = max(chunk, key=lambda p: p[1])
        if lo is hi:
            push(out, lo)
        else:
            first, second = (lo, hi) if lo[0] <= hi[0] else (hi, lo)
            push(out, first)
            push(out, second)
    push(out, points[-1])
    return out
