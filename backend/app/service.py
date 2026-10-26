"""점수 배치 계산(prior → strict → bayes) → scores 테이블, 그리고 반경 후보 조회.

- 엄격 별점·상위 N% 는 시군구(sigungu_code) 단위 분위수. 코드 없는 행(가상 시드)은 한 지역으로 묶음.
- 적재 후 전체 재계산, 리뷰 작성 시 해당 시군구만 재계산.
- 수동 재계산: python -m app.service
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from app.constants import PRICE_UNKNOWN
from app.scoring import bayes, prior, strict
from app.scoring.recommend import Candidate

ALL = object()
M_PER_DEG_LAT = 111_320


def _region_rows(conn: sqlite3.Connection, region) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.id, s.ext_rating, s.ad_ratio, s.ad_conf FROM restaurants r"
        " LEFT JOIN review_stats s ON s.restaurant_id = r.id"
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


def _user_reviews(conn: sqlite3.Connection, region) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    rows = conn.execute(
        "SELECT u.restaurant_id, u.stars FROM user_reviews u JOIN restaurants r ON r.id = u.restaurant_id"
        " WHERE r.sigungu_code IS ?",
        (region,),
    )
    for r in rows:
        out.setdefault(r["restaurant_id"], []).append(float(r["stars"]))
    return out


def _rebuild_region(conn: sqlite3.Connection, region, now: str) -> int:
    rows = _region_rows(conn, region)
    gov = _gov_info(conn, region)
    reviews = _user_reviews(conn, region)
    conn.execute(
        "DELETE FROM scores WHERE restaurant_id IN (SELECT id FROM restaurants WHERE sigungu_code IS ?)", (region,)
    )
    if not rows:
        return 0
    parts = [
        prior.prior_parts(
            prior.normalize_ext_rating(r["ext_rating"]),
            gov.get(r["id"], (0, None))[0],
            r["ad_ratio"] or 0.0,
            r["ad_conf"] or 0.0,
        )
        for r in rows
    ]
    prior_stars = strict.strict_map([p.prior_raw for p in parts])
    finals, means = [], []
    for r, ps in zip(rows, prior_stars):
        stars = reviews.get(r["id"], [])
        means.append(bayes.user_mean(stars))
        finals.append(bayes.final_star(ps, means[-1], len(stars)))
    pcts = strict.top_percents(finals)
    conn.executemany(
        "INSERT INTO scores(restaurant_id,prior_star,user_mean,n,star,percentile,gov_visits,gov_source,"
        "gov_bonus,ad_penalty,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r["id"], ps, round(um, 2) if um is not None else None, len(reviews.get(r["id"], [])), fs, pct,
                *gov.get(r["id"], (0, None)), round(p.gov_bonus, 4),
                round(p.ad_penalty, 4) if r["ad_ratio"] is not None else None, now,
            )
            for r, p, ps, um, fs, pct in zip(rows, parts, prior_stars, means, finals, pcts)
        ],
    )
    return len(rows)


def rebuild_scores(conn: sqlite3.Connection, region=ALL) -> int:
    """점수 재계산. region: 시군구 코드(None = 코드 없는 행), 기본은 전체."""
    now = datetime.now(timezone.utc).isoformat()
    regions = (
        [r[0] for r in conn.execute("SELECT DISTINCT sigungu_code FROM restaurants")] if region is ALL else [region]
    )
    n = sum(_rebuild_region(conn, reg, now) for reg in regions)
    conn.commit()
    return n


def region_of(conn: sqlite3.Connection, rid: str):
    return conn.execute("SELECT sigungu_code FROM restaurants WHERE id=?", (rid,)).fetchone()[0]


_SELECT = (
    "SELECT r.id, r.name, r.genre, r.price_band, r.moods, r.alcohol, r.lat, r.lng, r.updated_at,"
    " sc.prior_star, sc.user_mean, sc.n, sc.star, sc.percentile, sc.gov_visits, sc.gov_source,"
    " sc.gov_bonus, sc.ad_penalty FROM restaurants r JOIN scores sc ON sc.restaurant_id = r.id"
)


def _candidate(r: sqlite3.Row) -> Candidate:
    return Candidate(
        id=r["id"],
        name=r["name"],
        genre=r["genre"],
        price_band=r["price_band"] or PRICE_UNKNOWN,
        moods=[m for m in (r["moods"] or "").split("|") if m],
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
    )


def candidates_near(conn: sqlite3.Connection, lat: float, lng: float, radius_m: float) -> list[Candidate]:
    """반경을 감싸는 위경도 사각형 안의 영업 중 가게 (정확한 거리 필터는 recommend 에서)."""
    dlat = radius_m / M_PER_DEG_LAT
    dlng = radius_m / (M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    rows = conn.execute(
        _SELECT + " WHERE r.lat BETWEEN ? AND ? AND r.lng BETWEEN ? AND ?",
        (lat - dlat, lat + dlat, lng - dlng, lng + dlng),
    ).fetchall()
    return [_candidate(r) for r in rows]


def get_scored(conn: sqlite3.Connection, rid: str) -> tuple[Candidate, dict] | None:
    r = conn.execute(_SELECT + " WHERE r.id = ?", (rid,)).fetchone()
    if r is None:
        return None
    breakdown = {k: r[k] for k in ("prior_star", "user_mean", "n", "gov_bonus")}
    breakdown["k"] = bayes.K
    breakdown["ad_penalty"] = r["ad_penalty"] or 0.0
    return _candidate(r), breakdown


if __name__ == "__main__":
    from app import db

    c = db.connect()
    db.init_schema(c)
    print(f"scores: {rebuild_scores(c)}건 재계산")
