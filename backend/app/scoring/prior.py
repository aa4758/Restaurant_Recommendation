"""prior_raw 계산.

prior_raw = base
          + w_gov * min(log1p(gov_visits)/log1p(GOV_CAP), 1)
          - w_ad  * clamp((ad_ratio - AD_THRESHOLD)/AD_SPAN, 0, 1) * ad_conf

- base: 외부 평점 정규화(0~1).
- 업무추진비: log 감쇠 + 상한(GOV_CAP회 이상은 동일 보너스 = w_gov).
- 광고리뷰: 판별 신뢰도(ad_conf)가 낮으면 감점 축소. 하한(floor): 감점으로 인해
  base 의 AD_FLOOR_RATIO 미만으로는 떨어지지 않음(오분류 시 소상공인 보호).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

W_GOV = 0.25
GOV_CAP = 30
W_AD = 0.30
AD_THRESHOLD = 0.15
AD_SPAN = 0.5
AD_FLOOR_RATIO = 0.5  # 광고 감점 후에도 base 의 50% 는 보장

EXT_RATING_MIN = 1.0
EXT_RATING_MAX = 5.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def normalize_ext_rating(rating: float | None) -> float:
    """외부 평점(1~5) → 0~1. 결측이면 중립값 0.5."""
    if rating is None:
        return 0.5
    return clamp((rating - EXT_RATING_MIN) / (EXT_RATING_MAX - EXT_RATING_MIN), 0.0, 1.0)


def gov_bonus(gov_visits: int) -> float:
    visits = max(0, int(gov_visits or 0))
    return W_GOV * min(math.log1p(visits) / math.log1p(GOV_CAP), 1.0)


def ad_penalty_raw(ad_ratio: float, ad_conf: float) -> float:
    ratio = float(ad_ratio or 0.0)
    conf = clamp(float(ad_conf or 0.0), 0.0, 1.0)
    return W_AD * clamp((ratio - AD_THRESHOLD) / AD_SPAN, 0.0, 1.0) * conf


@dataclass(frozen=True)
class PriorParts:
    base: float
    gov_bonus: float
    ad_penalty: float  # floor 적용 후 실제 감점
    prior_raw: float


def prior_parts(base: float, gov_visits: int, ad_ratio: float, ad_conf: float) -> PriorParts:
    base = clamp(base, 0.0, 1.0)
    g = gov_bonus(gov_visits)
    p = ad_penalty_raw(ad_ratio, ad_conf)
    # floor: 광고 감점은 base*(1-AD_FLOOR_RATIO) 를 넘지 못함
    p = min(p, base * (1.0 - AD_FLOOR_RATIO))
    return PriorParts(base=base, gov_bonus=g, ad_penalty=p, prior_raw=base + g - p)


def prior_raw(base: float, gov_visits: int, ad_ratio: float, ad_conf: float) -> float:
    return prior_parts(base, gov_visits, ad_ratio, ad_conf).prior_raw
