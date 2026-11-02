"""엄격 스케일 매핑: 지역 내 분위수 → 0~5 별점 (평균≈2.5, 5.0 = 상위≈0.1%, 4.5 이상 상위≈0.7%).

분위수 p(중간순위, (rank-0.5)/N) 를 정규분포 역함수로 변환:
    star = clamp(MEAN + SIGMA * Φ⁻¹(p), 0, 5)
SIGMA = (5.0 - 2.5) / Φ⁻¹(0.999) ≈ 0.809 → 상위 0.1% 만 5.0 (v2.3, 2026-11-02 사용자 결정).
(v2.2 까지: SIGMA = 2.0 / Φ⁻¹(0.97) ≈ 1.063, 4.5 이상 상위 3% → 서울 5.0 표시 1,547곳으로 과다)
정규분포는 대칭이므로 평균은 2.5 로 수렴.
"""
from __future__ import annotations

from bisect import bisect_left
from statistics import NormalDist
from typing import Sequence

MEAN = 2.5
TOP_STAR = 5.0
TOP_SHARE = 0.001
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


def top_percents(values: Sequence[float]) -> list[int]:
    """각 값의 '이 지역 상위 N%' 의 N (1~100), O(n log n).
    동점은 동점 묶음의 가장 낮은 순위로 계산 → 근거 없이 모두 같은 점수일 때 "상위 1%" 과장 방지."""
    n = len(values)
    asc = sorted(values)
    out = []
    for v in values:
        rank = n - bisect_left(asc, v)  # 자신 이상인 값 수 = 동점 포함 최저 순위
        out.append(max(1, min(100, -(-rank * 100 // n))))
    return out
