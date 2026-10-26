"""prior_raw 계산 — 점수 모델 v2.1 (docs/01_planning_decision.md "점수 모델 v2" + "v2.1").

prior_raw = 0.30 * 업력      min(log1p(영업연수)/log1p(20), 1)     # opened_at, 없으면 0. 백년가게는 최소 30년 간주
          + 0.25 * 업무추진비  min(log1p(방문수)/log1p(30), 1)
          + 0.15 * 위생등급    매우우수 1 / 우수 0.7 / 좋음 0.4 / 없음 0
          + 0.10 * 지정업소    모범음식점·안심식당·원산지표시 우수 중 1개 이상이면 1
          + 0.20 * 외부 평판   max(가이드 선정 점수, 제휴 평점 0~1), 둘 다 없으면 0.4(중립)
          - 행정처분           기준일로부터 최근 3년(정확히 3년 전 당일 포함) 건당 0.05, 상한 0.15
          - 광고 감점          0.30 * clamp((ad_ratio-0.15)/0.5, 0, 1) * ad_conf
                               하한: 광고 감점 ≤ 가점 합계의 50% (오분류 시 소상공인 보호)
착한가격업소(good_price)는 점수 무관 — 조회 시 분위기 태그 '가성비' 합성(service).
근거 수준(evidence) = 데이터가 존재하는 신호 수 (가점은 값이 있으면 — 외부 평판은 가이드 또는 제휴 값이 있으면 포함
                   (기여 0 이어도), 결측 중립 0.4 제외 — 감점은 0보다 클 때만): 0 low / 1~2 mid / 3+ high

모든 함수는 순수 함수(DB·현재 시각 비의존). 영업연수·처분 기간은 기준일 인자 now 로 계산.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

# --- 가중치 / 상수 ---------------------------------------------------------
W_TENURE = 0.30
TENURE_CAP_YEARS = 20
W_GOV = 0.25
GOV_CAP = 30
W_HYGIENE = 0.15
HYGIENE_SCORES = {"매우우수": 1.0, "우수": 0.7, "좋음": 0.4}
HYGIENE_ALIASES = {"★★★": "매우우수", "★★": "우수", "★": "좋음", "3": "매우우수", "2": "우수", "1": "좋음"}
W_DESIGNATION = 0.10
DESIGNATION_KINDS = ("model_restaurant", "safe_restaurant", "origin_label_excellent")  # 위생·서비스 지정만
DESIGNATION_LABELS = {
    "model_restaurant": "모범음식점",
    "safe_restaurant": "안심식당",
    "origin_label_excellent": "원산지표시 우수",
}
CENTURY_KIND = "century_store"  # 백년가게: 업력 보정(외부 평판 아님)
CENTURY_LABEL = "백년가게"
CENTURY_MIN_YEARS = 30
GOOD_PRICE_KIND = "good_price"  # 착한가격업소: 점수 무관, 분위기 태그만
GOOD_PRICE_MOOD = "가성비"
W_REPUTATION = 0.20
REPUTATION_NEUTRAL = 0.4  # 가이드·제휴 모두 없을 때
# 외부 평판 가이드 점수 (restaurant_signals.kind). 미슐랭은 구조만 — 실데이터는 법무 확인 후 적재
GUIDE_SCORES = {
    "michelin_star": 1.0,
    "michelin_bib": 0.85,
    "taste_of_seoul": 0.85,
    "michelin_selected": 0.7,
    "seoul_future_heritage": 0.7,
    "local_food": 0.7,
}
GUIDE_LABELS = {
    "michelin_star": "미슐랭 가이드 스타",
    "michelin_bib": "미슐랭 빕 구르망",
    "taste_of_seoul": "서울미식 100선",
    "michelin_selected": "미슐랭 셀렉티드",
    "seoul_future_heritage": "서울미래유산",
    "local_food": "향토음식점",
}
MICHELIN_KINDS = ("michelin_star", "michelin_bib", "michelin_selected")
# 공공 신호 kind 전체 (적재 화이트리스트)
SIGNAL_KINDS = ("hygiene_grade", "sanction", *DESIGNATION_KINDS, CENTURY_KIND, GOOD_PRICE_KIND, *GUIDE_SCORES)
PARTNER_RATING_MIN = 1.0
PARTNER_RATING_MAX = 5.0
SANCTION_UNIT = 0.05
SANCTION_CAP = 0.15
SANCTION_YEARS = 3
W_AD = 0.30
AD_THRESHOLD = 0.15
AD_SPAN = 0.5
AD_FLOOR_RATIO = 0.5  # 광고 감점 ≤ 가점 합계 × 50%
AD_CONF_FULL_N = 10  # 자체 리뷰 10개면 판별 신뢰도 1
AD_KEYWORDS = ("체험단", "협찬", "제공받아", "원고료", "소정의")
# 광고 키워드 매칭. 키워드 직후 부정 표현("협찬 아님", "원고료 받지 않았", "광고·협찬 없이")이면 제외
AD_RE = re.compile(
    "(?:" + "|".join(AD_KEYWORDS) + r")(?!\s*(?:[은는이가을를도]\s*)?(?:아님|아닙|아니|없이|없음|없었|않|안\s*받|받지\s*않))"
)

COMPONENT_KEYS = ("tenure", "gov", "hygiene", "designation", "reputation", "sanction", "ad")


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def parse_date(s: str | date | None) -> date | None:
    """'YYYY-MM-DD' / 'YYYYMMDD' / 'YYYY.MM.DD' / ISO datetime → date. 실패 시 None."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    t = str(s).strip().replace(".", "-").replace("/", "-")
    if not t:
        return None
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:]}"
    try:
        return date.fromisoformat(t[:10])
    except ValueError:
        return None


def years_between(start: date, end: date) -> float:
    return max(0.0, (end - start).days / 365.2425)


def _years_ago(now: date, years: int) -> date:
    try:
        return now.replace(year=now.year - years)
    except ValueError:  # 2/29
        return now.replace(year=now.year - years, day=28)


# --- 구성요소 (0~1 정규화 점수) ---------------------------------------------
def tenure_years(opened_at: str | date | None, now: date) -> float | None:
    d = parse_date(opened_at)
    return None if d is None else years_between(d, now)


def tenure_score(opened_at: str | date | None, now: date, century_store: bool = False) -> float:
    """업력 점수. 백년가게면 영업연수를 최소 30년으로 간주(결측·짧을 때만 보정 → 이중 가점 없음)."""
    y = tenure_years(opened_at, now)
    if century_store:
        y = max(y or 0.0, float(CENTURY_MIN_YEARS))
    if not y:
        return 0.0
    return min(math.log1p(y) / math.log1p(TENURE_CAP_YEARS), 1.0)


def gov_score(gov_visits: int) -> float:
    visits = max(0, int(gov_visits or 0))
    return min(math.log1p(visits) / math.log1p(GOV_CAP), 1.0)


def gov_bonus(gov_visits: int) -> float:
    return W_GOV * gov_score(gov_visits)


def normalize_hygiene(grade: str | None) -> str | None:
    if not grade:
        return None
    g = str(grade).replace(" ", "").strip()
    g = HYGIENE_ALIASES.get(g, g)
    return g if g in HYGIENE_SCORES else None


def hygiene_score(grade: str | None) -> float:
    g = normalize_hygiene(grade)
    return HYGIENE_SCORES[g] if g else 0.0


def designation_score(kinds: Iterable[str] | None) -> float:
    return 1.0 if set(kinds or ()) & set(DESIGNATION_KINDS) else 0.0


def partner_score(rating: float | None) -> float | None:
    """제휴 평점(1~5) → 0~1. 결측이면 None."""
    if rating is None:
        return None
    return clamp((rating - PARTNER_RATING_MIN) / (PARTNER_RATING_MAX - PARTNER_RATING_MIN), 0.0, 1.0)


def guide_score(kinds: Iterable[str] | None) -> float | None:
    """가이드 선정 점수(여러 개면 최댓값). 없으면 None."""
    vals = [GUIDE_SCORES[k] for k in set(kinds or ()) if k in GUIDE_SCORES]
    return max(vals) if vals else None


def reputation_score(kinds: Iterable[str] | None, partner_rating: float | None) -> float:
    """외부 평판 = max(가이드 점수, 제휴 평점 0~1). 둘 다 없으면 중립 0.4."""
    vals = [v for v in (guide_score(kinds), partner_score(partner_rating)) if v is not None]
    return max(vals) if vals else REPUTATION_NEUTRAL


def has_reputation(kinds: Iterable[str] | None, partner_rating: float | None) -> bool:
    return guide_score(kinds) is not None or partner_rating is not None


def recent_sanctions(dates: Iterable[str | date | None], now: date, years: int = SANCTION_YEARS) -> int:
    """기준일로부터 최근 years 년 이내(정확히 years 년 전 당일 포함, 미래 제외) 처분 건수. 날짜 미상은 제외."""
    since = _years_ago(now, years)
    n = 0
    for s in dates or ():
        d = parse_date(s)
        if d is not None and since <= d <= now:  # 정확히 years 년 전 당일 포함
            n += 1
    return n


def sanction_penalty(count: int) -> float:
    return min(SANCTION_UNIT * max(0, int(count or 0)), SANCTION_CAP)


# --- 광고 리뷰 ------------------------------------------------------------
def is_ad_text(text: str | None) -> bool:
    return bool(text) and AD_RE.search(text) is not None


def ad_conf_from_count(n: int) -> float:
    return min(max(0, n) / AD_CONF_FULL_N, 1.0)


def own_ad_stats(texts: Sequence[str | None]) -> tuple[float, float] | None:
    """자체 리뷰 본문 → (광고 표시 비율, 신뢰도). 리뷰가 없으면 None."""
    if not texts:
        return None
    ads = sum(1 for t in texts if is_ad_text(t))
    return ads / len(texts), ad_conf_from_count(len(texts))


def pick_ad_signal(
    own: tuple[float, float] | None, partner: tuple[float, float] | None
) -> tuple[float, float] | None:
    """자체 통계와 제휴 통계 중 신뢰도(conf)가 높은 쪽. 둘 다 없으면 None."""
    cands = [s for s in (own, partner) if s is not None]
    if not cands:
        return None
    return max(cands, key=lambda s: s[1])


def ad_penalty_raw(ad_ratio: float, ad_conf: float) -> float:
    ratio = float(ad_ratio or 0.0)
    conf = clamp(float(ad_conf or 0.0), 0.0, 1.0)
    return W_AD * clamp((ratio - AD_THRESHOLD) / AD_SPAN, 0.0, 1.0) * conf


def evidence_level(signal_count: int) -> str:
    if signal_count <= 0:
        return "low"
    return "mid" if signal_count <= 2 else "high"


@dataclass(frozen=True)
class PriorParts:
    components: dict[str, float]  # 가중 적용 기여분. 감점(sanction, ad)은 음수. 합계 = prior_raw
    gov_bonus: float
    ad_penalty: float  # 하한 적용 후 실제 감점(양수)
    prior_raw: float
    evidence: str  # low | mid | high


def prior_parts(
    *,
    now: date,
    opened_at: str | date | None = None,
    gov_visits: int = 0,
    hygiene_grade: str | None = None,
    designations: Iterable[str] | None = None,  # 공공 신호 kind 목록(지정업소·가이드·백년가게·착한가격 혼재 가능)
    partner_rating: float | None = None,
    sanction_dates: Iterable[str | date | None] | None = None,
    ad_ratio: float | None = None,
    ad_conf: float = 0.0,
) -> PriorParts:
    kinds = set(designations or ())
    t = W_TENURE * tenure_score(opened_at, now, century_store=CENTURY_KIND in kinds)
    g = W_GOV * gov_score(gov_visits)
    h = W_HYGIENE * hygiene_score(hygiene_grade)
    d = W_DESIGNATION * designation_score(kinds)
    p = W_REPUTATION * reputation_score(kinds, partner_rating)
    s = sanction_penalty(recent_sanctions(sanction_dates or (), now))
    plus = t + g + h + d + p
    a = 0.0 if ad_ratio is None else min(ad_penalty_raw(ad_ratio, ad_conf), plus * AD_FLOOR_RATIO)
    components = {
        "tenure": t, "gov": g, "hygiene": h, "designation": d, "reputation": p, "sanction": -s, "ad": -a,
    }
    signals = sum(1 for v in (t, g, h, d, s, a) if v > 0) + has_reputation(kinds, partner_rating)
    return PriorParts(
        components=components,
        gov_bonus=g,
        ad_penalty=a,
        prior_raw=plus - s - a,
        evidence=evidence_level(signals),
    )


def prior_raw(**kw) -> float:
    return prior_parts(**kw).prior_raw
