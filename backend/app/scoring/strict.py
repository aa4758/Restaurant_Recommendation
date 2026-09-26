"""엄격 스케일 매핑: 지역 내 분위수 → 0~5 별점 (평균≈2.5, 4.5 이상 상위≈3%).

분위수 p(중간순위, (rank-0.5)/N) 를 정규분포 역함수로 변환:
    star = clamp(MEAN + SIGMA * Φ⁻¹(p), 0, 5)
SIGMA = (4.5 - 2.5) / Φ⁻¹(0.97) ≈ 1.063 → 상위 3% 가 4.5 이상.
정규분포는 대칭이므로 평균은 2.5 로 수렴.
"""
from __future__ import annotations

from statistics import NormalDist
from typing import Sequence

MEAN = 2.5
TOP_STAR = 4.5
TOP_SHARE = 0.03
_N = NormalDist()
SIGMA = (TOP_STAR - MEAN) / _N.inv_cdf(1 - TOP_SHARE)


def quantiles(values: Sequence[float]) -> list[float]:
    """각 값의 지역 내 분위수(0~1, 동점은 평균 순위)."""
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: values[i])
    q = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        mid_rank = (i + j) / 2 + 1  # 1-based 평균 순위
        for t in range(i, j + 1):
            q[order[t]] = (mid_rank - 0.5) / n
        i = j + 1
    return q


def star_from_quantile(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return round(min(5.0, max(0.0, MEAN + SIGMA * _N.inv_cdf(p))), 2)


def strict_map(values: Sequence[float]) -> list[float]:
    """prior_raw 목록(같은 지역) → 엄격 별점 목록."""
    return [star_from_quantile(p) for p in quantiles(values)]


def top_percent(value: float, population: Sequence[float]) -> int:
    """'이 지역 상위 N%' 의 N (1~100). 자신보다 높은 값 수 기준."""
    n = len(population)
    if n == 0:
        return 100
    higher = sum(1 for v in population if v > value)
    return max(1, min(100, int(-(-(higher + 1) * 100 // n))))
