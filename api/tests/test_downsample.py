"""Тесты даунсемплинга (ТЗ §8.3: ≤1500 точек)."""

from app.query import MAX_POINTS, downsample


def test_short_series_unchanged():
    pts = [[i, float(i)] for i in range(10)]
    assert downsample(pts) is pts


def test_bucketed_count_and_order():
    n = 10_000
    pts = [[i, float(i % 50)] for i in range(n)]
    out = downsample(pts)
    assert len(out) <= MAX_POINTS
    ts = [p[0] for p in out]
    assert ts == sorted(ts)


def test_mean_per_bucket():
    # span 100, max 10 → size 12; первый бакет [0, 12): среднее 0..11 = 5.5
    pts = [[t, float(t)] for t in range(0, 101)]
    out = downsample(pts, max_points=10)
    assert out[0] == [6.0, 5.5]


def test_gap_preserved():
    # разрыв [1000, 2000) не должен заполнить пунктами
    pts = [[i, 1.0] for i in range(0, 1000)] + [[i, 1.0] for i in range(2000, 3000)]
    out = downsample(pts)
    assert not any(1300 <= p[0] < 1800 for p in out)


def test_constant_series():
    pts = [[i, 7.0] for i in range(2000)]
    out = downsample(pts)
    assert all(p[1] == 7.0 for p in out)
    assert len(out) <= MAX_POINTS
