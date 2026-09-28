"""Тесты даунсемплинга (ТЗ §8.3: ≤1500 точек)."""

import math

from app.query import MAX_POINTS, downsample


def test_short_series_unchanged():
    pts = [[i, float(i)] for i in range(10)]
    assert downsample(pts) is pts


def test_slightly_over_max():
    # n чуть больше лимита: ≤ ~2*(max_points//2) точек, а не «пара точек»
    n = 1800
    pts = [[i, float(i)] for i in range(n)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS + 10
    assert len(out) >= n // 2
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


def test_large_series_bound():
    n = 100_000
    pts = [[i, math.sin(i / 100.0)] for i in range(n)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS + 10
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]


def test_bounds_and_shape():
    n = 5000
    pts = [[i, math.sin(i / 50.0)] for i in range(n)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS
    # края сохранены
    assert out[0] == pts[0]
    assert out[-1] == pts[-1]
    # глобальные экстремумы не потеряны
    gmin = min(pts, key=lambda p: p[1])
    gmax = max(pts, key=lambda p: p[1])
    values = [p[1] for p in out]
    assert gmin[1] in values
    assert gmax[1] in values
    # порядок времени не нарушен
    ts = [p[0] for p in out]
    assert ts == sorted(ts)


def test_spike_preserved():
    # всплеск в середине ряда обязан выжить
    pts = [[i, 1.0] for i in range(3000)]
    pts[1500] = [1500, 100.0]
    out = downsample(pts)
    assert any(p[1] == 100.0 for p in out)
    assert len(out) <= MAX_POINTS
