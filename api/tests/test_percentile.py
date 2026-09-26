"""Тесты kвантилей по buckets (метод ТЗ §5.2 — интерполяция)."""

import math

from app.collectors.percentile import percentile_from_buckets


def test_interpolation_inside_bucket():
    # cumulative: (2, 2481), (5, 2868), total 2948; p95 → 2 + 3 * (2800.6-2481)/(2868-2481)
    buckets = [
        (0.01, 355),
        (0.1, 1047),
        (0.5, 1499),
        (1.0, 1659),
        (2.0, 2481),
        (5.0, 2868),
        (math.inf, 2948),
    ]
    p95 = percentile_from_buckets(buckets, 0.95)
    assert p95 == 2 + 3 * ((0.95 * 2948 - 2481) / (2868 - 2481))


def test_first_bucket_lower_bound_zero():
    buckets = [(1.0, 100.0), (math.inf, 100.0)]
    # доля 0.5 целиком в первом bucket'е → интерполяция от 0
    assert percentile_from_buckets(buckets, 0.5) == 0.5


def test_p100_falls_into_inf():
    buckets = [(1.0, 50.0), (2.0, 100.0), (math.inf, 100.0)]
    assert percentile_from_buckets(buckets, 1.0) == 2.0


def test_p0():
    buckets = [(1.0, 10.0), (math.inf, 10.0)]
    assert percentile_from_buckets(buckets, 0.0) == 0.0


def test_empty_and_bad_input():
    assert percentile_from_buckets([], 0.95) is None
    assert percentile_from_buckets([(1.0, 0.0), (math.inf, 0.0)], 0.95) is None
    assert percentile_from_buckets([(1.0, 10.0)], 1.5) is None


def test_unsorted_buckets():
    buckets = [(math.inf, 30.0), (0.5, 10.0), (1.0, 25.0)]
    # p50 → доля 15; (0.5,10) нет, (1.0,25) да: 0.5 + 0.5 * (15-10)/15
    expected = 0.5 + 0.5 * (15 - 10) / (25 - 10)
    assert percentile_from_buckets(buckets, 0.5) == expected
