"""추천: 필터 → 완화(거리→분위기→가격→장르, 음주는 불완화) → rank_score → 동점대 로테이션 → reasons.

rank_score = final_star + 조건적합도 보너스 - 거리 패널티
- 조건적합도 보너스: 사용자가 지정한 조건(가격/장르/분위기) 중 충족한 항목당 FIT_BONUS.
  (완화되지 않은 조건은 모두 충족하므로, 완화된 조건을 여전히 만족하는 곳이 우대됨)
- 거리 패널티: DIST_PENALTY * distance_m / 원래 반경 (반경 끝에서 0.3)
- 동점대: 선두 점수와 ±TIE_BAND 이내 묶음은 날짜 시드로 일 단위 셔플.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

FIT_BONUS = 0.1
DIST_PENALTY = 0.3
TIE_BAND = 0.1
RELAX_ORDER = ("distance", "mood", "price", "genre")  # 음주(alcohol)는 완화하지 않음
DISTANCE_RELAX_FACTOR = 2
MAX_LIMIT = 5
WALK_M_PER_MIN = 80


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Candidate:
    id: str
    name: str
    genre: str
    price_band: str
    moods: list[str]
    alcohol: bool
    lat: float
    lng: float
    star: float
    percentile: int
    review_count: int = 0
    gov_visits: int = 0
    gov_source: str | None = None
    ad_penalty: float | None = None  # None = 광고 리뷰 통계 없음
    updated_at: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Query:
    lat: float
    lng: float
    radius_m: int = 1000
    price: list[str] | None = None
    genre: list[str] | None = None
    mood: list[str] | None = None
    alcohol: str = "any"
    limit: int = 3


@dataclass
class Scored:
    cand: Candidate
    distance_m: float | None
    rank_score: float
    reasons: list[str] = field(default_factory=list)


def _alcohol_ok(c: Candidate, alcohol: str) -> bool:
    if alcohol == "yes":
        return c.alcohol
    if alcohol == "no":
        return not c.alcohol
    return True


def _matches(c: Candidate, dist: float, q: Query, relaxed: set[str]) -> bool:
    if not _alcohol_ok(c, q.alcohol):
        return False
    radius = q.radius_m * (DISTANCE_RELAX_FACTOR if "distance" in relaxed else 1)
    if dist > radius:
        return False
    if q.mood and "mood" not in relaxed and not set(q.mood) & set(c.moods):
        return False
    if q.price and "price" not in relaxed and c.price_band not in q.price:
        return False
    if q.genre and "genre" not in relaxed and c.genre not in q.genre:
        return False
    return True


def _fit_count(c: Candidate, q: Query) -> int:
    n = 0
    if q.mood and set(q.mood) & set(c.moods):
        n += 1
    if q.price and c.price_band in q.price:
        n += 1
    if q.genre and c.genre in q.genre:
        n += 1
    return n


def rank_score(c: Candidate, dist: float, q: Query) -> float:
    return c.star + FIT_BONUS * _fit_count(c, q) - DIST_PENALTY * dist / max(q.radius_m, 1)


def _relaxable(q: Query) -> list[str]:
    out = []
    for key in RELAX_ORDER:
        if key == "distance" or getattr(q, key):
            out.append(key)
    return out


def rotate_ties(items: list[Scored], day: date, band: float = TIE_BAND) -> list[Scored]:
    """점수 내림차순 목록에서 선두 대비 ±band 묶음을 날짜 시드로 셔플."""
    items = sorted(items, key=lambda s: (-s.rank_score, s.cand.id))
    out: list[Scored] = []
    i = 0
    while i < len(items):
        lead = items[i].rank_score
        j = i
        while j + 1 < len(items) and lead - items[j + 1].rank_score <= band + 1e-9:
            j += 1
        group = items[i : j + 1]
        if len(group) > 1:
            key = day.isoformat() + "|" + ",".join(s.cand.id for s in group)
            seed = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
            random.Random(seed).shuffle(group)
        out.extend(group)
        i = j + 1
    return out


def make_reasons(s: Scored, q: Query) -> list[str]:
    c = s.cand
    line1 = f"엄격 별점 {c.star:.1f} · 이 지역 상위 {c.percentile}%"
    fit = []
    if q.genre and c.genre in q.genre:
        fit.append(f"{c.genre}")
    if q.price and c.price_band in q.price:
        fit.append(f"가격 {c.price_band}")
    matched_moods = [m for m in c.moods if q.mood and m in q.mood]
    if matched_moods:
        fit.append("/".join(matched_moods) + " 분위기")
    if q.alcohol == "yes" and c.alcohol:
        fit.append("음주 가능")
    elif q.alcohol == "no" and not c.alcohol:
        fit.append("비주류 매장")
    if s.distance_m is None:  # 위치 미지정(상세 조회)
        line2 = " · ".join([c.genre, c.price_band] + (["/".join(c.moods)] if c.moods else []))
    else:
        walk = max(1, round(s.distance_m / WALK_M_PER_MIN))
        fit_txt = " · ".join(fit) if fit else f"{c.genre} · {c.price_band}"
        line2 = f"도보 약 {walk}분({int(round(s.distance_m))}m) · {fit_txt}"
    if c.gov_visits > 0:
        src = f"({c.gov_source})" if c.gov_source else ""
        line3 = f"공공기관 업무추진비 기록 {c.gov_visits}회{src}"
    elif c.review_count > 0:
        line3 = f"찐맛 자체 리뷰 {c.review_count}개 반영"
    elif c.ad_penalty is not None and c.ad_penalty <= 0:
        line3 = "광고·체험단 리뷰 비율 낮음"
    else:
        line3 = "외부 평점 기반 사전 점수(자체 리뷰 축적 전)"
    return [line1, line2, line3]


def recommend(
    candidates: Iterable[Candidate], q: Query, day: date | None = None
) -> tuple[list[Scored], list[str]]:
    """반환: (추천 목록, 완화된 조건 목록)."""
    day = day or date.today()
    limit = max(1, min(MAX_LIMIT, q.limit))
    with_dist = [(c, haversine_m(q.lat, q.lng, c.lat, c.lng)) for c in candidates]

    relaxed: list[str] = []
    steps = _relaxable(q)
    while True:
        rs = set(relaxed)
        hits = [(c, d) for c, d in with_dist if _matches(c, d, q, rs)]
        if len(hits) >= limit or not steps:
            break
        relaxed.append(steps.pop(0))

    scored = [Scored(c, d, rank_score(c, d, q)) for c, d in hits]
    ordered = rotate_ties(scored, day)[:limit]
    for s in ordered:
        s.reasons = make_reasons(s, q)
    return ordered, relaxed
