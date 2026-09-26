"""DB → 점수 계산(prior → strict → bayes) → 후보 목록."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.constants import PRICE_UNKNOWN
from app.scoring import bayes, prior, strict
from app.scoring.recommend import Candidate


@dataclass
class Scored:
    cand: Candidate
    breakdown: dict


def _gov_info(conn: sqlite3.Connection) -> dict[str, tuple[int, str | None]]:
    out: dict[str, tuple[int, str | None]] = {}
    rows = conn.execute(
        "SELECT restaurant_id, COUNT(*) AS n, MAX(base_year) AS yr,"
        " GROUP_CONCAT(DISTINCT source) AS src FROM gov_expense GROUP BY restaurant_id"
    ).fetchall()
    for r in rows:
        src = r["src"] or "공공기관 업무추진비 공개"
        label = f"{src}·{r['yr']}" if r["yr"] else src
        out[r["restaurant_id"]] = (int(r["n"]), label)
    return out


def _user_reviews(conn: sqlite3.Connection) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in conn.execute("SELECT restaurant_id, stars FROM user_reviews"):
        out.setdefault(r["restaurant_id"], []).append(float(r["stars"]))
    return out


def load_scored(conn: sqlite3.Connection) -> dict[str, Scored]:
    rows = conn.execute(
        "SELECT r.*, s.ext_rating, s.ad_ratio, s.ad_conf FROM restaurants r"
        " LEFT JOIN review_stats s ON s.restaurant_id = r.id WHERE r.status = 'open' ORDER BY r.id"
    ).fetchall()
    if not rows:
        return {}
    gov = _gov_info(conn)
    reviews = _user_reviews(conn)

    parts = []
    for r in rows:
        visits = gov.get(r["id"], (0, None))[0]
        parts.append(
            prior.prior_parts(
                prior.normalize_ext_rating(r["ext_rating"]), visits, r["ad_ratio"] or 0.0, r["ad_conf"] or 0.0
            )
        )
    prior_stars = strict.strict_map([p.prior_raw for p in parts])

    finals = []
    for r, ps in zip(rows, prior_stars):
        stars = reviews.get(r["id"], [])
        finals.append(bayes.final_star(ps, bayes.user_mean(stars), len(stars)))

    out: dict[str, Scored] = {}
    for r, p, ps, fs in zip(rows, parts, prior_stars, finals):
        stars = reviews.get(r["id"], [])
        visits, src = gov.get(r["id"], (0, None))
        um = bayes.user_mean(stars)
        cand = Candidate(
            id=r["id"],
            name=r["name"],
            genre=r["genre"],
            price_band=r["price_band"] or PRICE_UNKNOWN,
            moods=[m for m in (r["moods"] or "").split("|") if m],
            alcohol=bool(r["alcohol"]),
            lat=r["lat"],
            lng=r["lng"],
            star=fs,
            percentile=strict.top_percent(fs, finals),
            review_count=len(stars),
            gov_visits=visits,
            gov_source=src,
            ad_penalty=p.ad_penalty if r["ad_ratio"] is not None else None,
            updated_at=r["updated_at"] or "",
        )
        out[r["id"]] = Scored(
            cand,
            {
                "prior_star": ps,
                "user_mean": round(um, 2) if um is not None else None,
                "n": len(stars),
                "k": bayes.K,
                "gov_bonus": round(p.gov_bonus, 4),
                "ad_penalty": round(p.ad_penalty, 4),
            },
        )
    return out
