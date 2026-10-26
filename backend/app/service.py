"""점수 배치 계산(prior v2.1 → strict → bayes) → scores 테이블, 그리고 반경 후보 조회.

- 신호(업무추진비·공공 신호·자체 리뷰)는 시군구 단위로 한 번에 조회 → 가게별 쿼리 없음.
- 행정처분은 기준일(today) 기준 최근 3년, 자체 리뷰 광고 비율은 본문 키워드(prior.AD_KEYWORDS) 집계.

- 엄격 별점·상위 N% 는 시군구(sigungu_code) 단위 분위수. 코드 없는 행(가상 시드)은 한 지역으로 묶음.
- 적재 후 전체 재계산, 리뷰 작성 시 해당 시군구만 재계산.
- 수동 재계산: python -m app.service
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.constants import PRICE_UNKNOWN
from app.scoring import bayes, prior, strict
from app.scoring.recommend import Candidate

ALL = object()
M_PER_DEG_LAT = 111_320


def _region_rows(conn: sqlite3.Connection, region) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.id, r.opened_at, s.restaurant_id AS has_stats, s.ext_rating, s.ad_ratio, s.ad_conf"
        " FROM restaurants r LEFT JOIN review_stats s ON s.restaurant_id = r.id"
        " WHERE r.status = 'open' AND r.sigungu_code IS ? ORDER BY r.id",
        (region,),
    ).fetchall()


def _gov_info(conn: sqlite3.Connection, region) -> dict[str, tuple[int, str | None]]:
    out: dict[str, tuple[int, str | None]] = {}
    rows = conn.execute(
        "SELECT g.restaurant_id, COUNT(*) AS n, MAX(g.base_year) AS yr, GROUP_CONCAT(DISTINCT g.source) AS src"
        " FROM gov_expense g JOIN restaurants r ON r.id = g.restaurant_id"
        " WHERE r.sigungu_code IS ? GROUP BY g.restaurant_id",
        (region,),
    ).fetchall()
    for r in rows:
        src = r["src"] or "공공기관 업무추진비 공개"
        label = f"{src}·{r['yr']}" if r["yr"] else src
        out[r["restaurant_id"]] = (int(r["n"]), label)
    return out


@dataclass
class Signals:
    hygiene: str | None = None  # 최신 위생등급 (매우우수|우수|좋음)
    designations: set[str] = field(default_factory=set)  # 지정업소·가이드·백년가게·착한가격 kind
    guide_years: dict[str, int | None] = field(default_factory=dict)  # 가이드 kind → 최신 기준연도
    sanction_dates: list[str | None] = field(default_factory=list)


def _signals(conn: sqlite3.Connection, where: str, params: tuple) -> dict[str, Signals]:
    """공공 신호를 한 번의 쿼리로 묶어 조회(가게별 N+1 금지). where 는 restaurants r 기준 조건."""
    out: dict[str, Signals] = {}
    rows = conn.execute(
        "SELECT g.restaurant_id, g.kind, g.value, g.base_date FROM restaurant_signals g"
        " JOIN restaurants r ON r.id = g.restaurant_id WHERE " + where +
        " ORDER BY g.restaurant_id, g.base_date",  # 날짜 오름차순 → 마지막 위생등급이 최신
        params,
    )
    for r in rows:
        sig = out.setdefault(r["restaurant_id"], Signals())
        kind = r["kind"]
        if kind == "hygiene_grade":
            grade = prior.normalize_hygiene(r["value"])
            if grade:
                sig.hygiene = grade
        elif kind == "sanction":
            sig.sanction_dates.append(r["base_date"])
        elif kind in prior.SIGNAL_KINDS:
            sig.designations.add(kind)
            if kind in prior.GUIDE_SCORES:
                d = prior.parse_date(r["base_date"])
                prev = sig.guide_years.get(kind)
                sig.guide_years[kind] = max(filter(None, (prev, d.year if d else None)), default=None)
    return out


def _user_reviews(conn: sqlite3.Connection, region) -> dict[str, list[tuple[float, str | None]]]:
    out: dict[str, list[tuple[float, str | None]]] = {}
    rows = conn.execute(
        "SELECT u.restaurant_id, u.stars, u.text FROM user_reviews u JOIN restaurants r ON r.id = u.restaurant_id"
        " WHERE r.sigungu_code IS ?",
        (region,),
    )
    for r in rows:
        out.setdefault(r["restaurant_id"], []).append((float(r["stars"]), r["text"]))
    return out


def _prior_for(r: sqlite3.Row, gov_visits: int, sig: Signals, reviews: list[tuple[float, str | None]], today: date):
    partner_ad = (float(r["ad_ratio"] or 0.0), float(r["ad_conf"] or 0.0)) if r["has_stats"] else None
    ad = prior.pick_ad_signal(prior.own_ad_stats([t for _, t in reviews]), partner_ad)
    return prior.prior_parts(
        now=today,
        opened_at=r["opened_at"],
        gov_visits=gov_visits,
        hygiene_grade=sig.hygiene,
        designations=sig.designations,
        partner_rating=r["ext_rating"],
        sanction_dates=sig.sanction_dates,
        ad_ratio=ad[0] if ad else None,
        ad_conf=ad[1] if ad else 0.0,
    )


def _rebuild_region(conn: sqlite3.Connection, region, now: str, today: date) -> int:
    rows = _region_rows(conn, region)
    gov = _gov_info(conn, region)
    sigs = _signals(conn, "r.sigungu_code IS ?", (region,))
    reviews = _user_reviews(conn, region)
    conn.execute(
        "DELETE FROM scores WHERE restaurant_id IN (SELECT id FROM restaurants WHERE sigungu_code IS ?)", (region,)
    )
    if not rows:
        return 0
    parts = [
        _prior_for(r, gov.get(r["id"], (0, None))[0], sigs.get(r["id"], Signals()), reviews.get(r["id"], []), today)
        for r in rows
    ]
    prior_stars = strict.strict_map([p.prior_raw for p in parts])
    finals, means = [], []
    for r, ps in zip(rows, prior_stars):
        stars = [s for s, _ in reviews.get(r["id"], [])]
        means.append(bayes.user_mean(stars))
        finals.append(bayes.final_star(ps, means[-1], len(stars)))
    pcts = strict.top_percents(finals)
    conn.executemany(
        "INSERT INTO scores(restaurant_id,prior_star,user_mean,n,star,percentile,gov_visits,gov_source,"
        "gov_bonus,ad_penalty,components,evidence,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r["id"], ps, round(um, 2) if um is not None else None, len(reviews.get(r["id"], [])), fs, pct,
                *gov.get(r["id"], (0, None)), round(p.gov_bonus, 4),
                round(p.ad_penalty, 4) if (r["has_stats"] or reviews.get(r["id"])) else None,
                json.dumps({k: round(v, 4) + 0.0 for k, v in p.components.items()}), p.evidence, now,
            )
            for r, p, ps, um, fs, pct in zip(rows, parts, prior_stars, means, finals, pcts)
        ],
    )
    return len(rows)


def utc_today() -> date:
    """점수 재계산·표시용 업력의 공통 기준일(UTC 날짜)."""
    return datetime.now(timezone.utc).date()


def rebuild_scores(conn: sqlite3.Connection, region=ALL, today: date | None = None) -> int:
    """점수 재계산. region: 시군구 코드(None = 코드 없는 행), 기본은 전체. today: 업력·처분 기준일(기본 오늘)."""
    ts = datetime.now(timezone.utc)
    now = ts.isoformat()
    today = today or ts.date()  # = utc_today()
    regions = (
        [r[0] for r in conn.execute("SELECT DISTINCT sigungu_code FROM restaurants")] if region is ALL else [region]
    )
    n = sum(_rebuild_region(conn, reg, now, today) for reg in regions)
    conn.commit()
    return n


def region_of(conn: sqlite3.Connection, rid: str):
    return conn.execute("SELECT sigungu_code FROM restaurants WHERE id=?", (rid,)).fetchone()[0]


_SELECT = (
    "SELECT r.id, r.name, r.genre, r.price_band, r.moods, r.alcohol, r.lat, r.lng, r.updated_at,"
    " sc.prior_star, sc.user_mean, sc.n, sc.star, sc.percentile, sc.gov_visits, sc.gov_source,"
    " sc.gov_bonus, sc.ad_penalty, sc.components, sc.evidence, r.opened_at FROM restaurants r JOIN scores sc ON sc.restaurant_id = r.id"
)


def guide_labels(sig: Signals) -> list[str]:
    """가이드 선정 문구(점수 높은 순): '서울미식 100선 선정(2025)' — 연도는 base_date 기준."""
    kinds = sorted(sig.guide_years, key=lambda k: (-prior.GUIDE_SCORES[k], k))
    return [
        f"{prior.GUIDE_LABELS[k]} 선정" + (f"({sig.guide_years[k]})" if sig.guide_years[k] else "") for k in kinds
    ]


def display_moods(raw: str | None, sig: Signals) -> list[str]:
    """원본 moods + 착한가격업소면 '가성비' 합성(원본 컬럼은 수정하지 않음, 필터 매칭에도 사용)."""
    moods = [m for m in (raw or "").split("|") if m]
    if prior.GOOD_PRICE_KIND in sig.designations and prior.GOOD_PRICE_MOOD not in moods:
        moods.append(prior.GOOD_PRICE_MOOD)
    return moods


def _candidate(r: sqlite3.Row, sig: Signals | None = None, today: date | None = None) -> Candidate:
    sig = sig or Signals()
    years = prior.tenure_years(r["opened_at"], today or utc_today())  # rebuild_scores 와 같은 기준일
    return Candidate(
        id=r["id"],
        name=r["name"],
        genre=r["genre"],
        price_band=r["price_band"] or PRICE_UNKNOWN,
        moods=display_moods(r["moods"], sig),
        alcohol=bool(r["alcohol"]),
        lat=r["lat"],
        lng=r["lng"],
        star=r["star"],
        percentile=r["percentile"],
        review_count=r["n"],
        gov_visits=r["gov_visits"],
        gov_source=r["gov_source"],
        ad_penalty=r["ad_penalty"],
        updated_at=r["updated_at"] or "",
        tenure_years=int(years) if years is not None else None,
        hygiene_grade=sig.hygiene,
        designations=[prior.DESIGNATION_LABELS[k] for k in prior.DESIGNATION_KINDS if k in sig.designations],
        guides=guide_labels(sig),
        century_store=prior.CENTURY_KIND in sig.designations,
        evidence=r["evidence"],
    )


def candidates_near(
    conn: sqlite3.Connection, lat: float, lng: float, radius_m: float, today: date | None = None
) -> list[Candidate]:
    """반경을 감싸는 위경도 사각형 안의 영업 중 가게 (정확한 거리 필터는 recommend 에서)."""
    dlat = radius_m / M_PER_DEG_LAT
    dlng = radius_m / (M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    where = "r.lat BETWEEN ? AND ? AND r.lng BETWEEN ? AND ?"
    params = (lat - dlat, lat + dlat, lng - dlng, lng + dlng)
    rows = conn.execute(_SELECT + " WHERE " + where, params).fetchall()
    sigs = _signals(conn, where, params)  # 반경 사각형 단위 1회 조회
    today = today or utc_today()
    return [_candidate(r, sigs.get(r["id"]), today) for r in rows]


def get_scored(conn: sqlite3.Connection, rid: str, today: date | None = None) -> tuple[Candidate, dict] | None:
    r = conn.execute(_SELECT + " WHERE r.id = ?", (rid,)).fetchone()
    if r is None:
        return None
    breakdown = {k: r[k] for k in ("prior_star", "user_mean", "n", "gov_bonus")}
    breakdown["k"] = bayes.K
    breakdown["ad_penalty"] = r["ad_penalty"] or 0.0
    # 재계산 전(NULL)이면 null 로 응답 → 클라이언트는 기존 표시로 fallback
    comps = json.loads(r["components"]) if r["components"] else None
    breakdown["components"] = {k: float(comps.get(k, 0.0)) for k in prior.COMPONENT_KEYS} if comps else None
    breakdown["evidence"] = r["evidence"]
    return _candidate(r, _signals(conn, "r.id = ?", (rid,)).get(rid), today or utc_today()), breakdown


if __name__ == "__main__":
    from app import db

    c = db.connect()
    db.init_schema(c)
    print(f"scores: {rebuild_scores(c)}건 재계산")
