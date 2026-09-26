"""베이지안 수축: prior 를 가상 리뷰 k=20 개로 취급.

final_star = (k*prior_star + n*user_mean) / (k + n)
"""
from __future__ import annotations

from typing import Sequence

K = 20


def user_mean(stars: Sequence[float]) -> float | None:
    return (sum(stars) / len(stars)) if stars else None


def final_star(prior_star: float, mean: float | None, n: int, k: int = K) -> float:
    if n <= 0 or mean is None:
        return round(prior_star, 2)
    return round((k * prior_star + n * mean) / (k + n), 2)


def prior_weight(n: int, k: int = K) -> float:
    return k / (k + max(0, n))
