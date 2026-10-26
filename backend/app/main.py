"""찐맛(JJINMAT) 백엔드 API. 계약: docs/01_planning_decision.md 'API 계약'."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.constants import ALCOHOL, GENRES, MOODS, PRICE_BANDS
from app.schemas import (
    Item,
    RecommendRequest,
    RecommendResponse,
    ReportIn,
    RestaurantDetail,
    ReviewIn,
    ReviewOut,
)
from app.scoring.recommend import DISTANCE_RELAX_FACTOR, Query, Scored as RecScored, make_reasons, recommend
from app.service import candidates_near, get_scored, rebuild_scores, region_of

app = FastAPI(title="JJINMAT API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_conn() -> Iterator:
    conn = db.connect()
    db.init_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def today() -> date:
    return date.today()


def _item_dict(s: RecScored) -> dict:
    c = s.cand
    return {
        "id": c.id,
        "name": c.name,
        "genre": c.genre,
        "price_band": c.price_band,
        "moods": c.moods,
        "alcohol": c.alcohol,
        "lat": c.lat,
        "lng": c.lng,
        "distance_m": int(round(s.distance_m)) if s.distance_m is not None else None,
        "star": c.star,
        "percentile": c.percentile,
        "review_count": c.review_count,
        "gov_visits": c.gov_visits,
        "gov_source": c.gov_source,
        "reasons": s.reasons,
        "updated_at": c.updated_at,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/meta/filters")
def meta_filters() -> dict:
    return {"price": PRICE_BANDS, "genre": GENRES, "mood": MOODS, "alcohol": ALCOHOL}


@app.post("/recommend", response_model=RecommendResponse)
def post_recommend(req: RecommendRequest, conn=Depends(get_conn), day: date = Depends(today)) -> dict:
    q = Query(**req.model_dump())
    # 완화 시 반경이 DISTANCE_RELAX_FACTOR 배까지 늘어나므로 그만큼 조회
    cands = candidates_near(conn, q.lat, q.lng, q.radius_m * DISTANCE_RELAX_FACTOR)
    items, relaxed = recommend(cands, q, day=day)
    return {"items": [_item_dict(s) for s in items], "relaxed": relaxed}


def _require(conn, rid: str) -> None:
    if not conn.execute("SELECT 1 FROM restaurants WHERE id=?", (rid,)).fetchone():
        raise HTTPException(status_code=404, detail="restaurant not found")


@app.get("/restaurants/{rid}", response_model=RestaurantDetail)
def get_restaurant(rid: str, conn=Depends(get_conn)) -> dict:
    found = get_scored(conn, rid)
    if found is None:
        raise HTTPException(status_code=404, detail="restaurant not found")
    cand, breakdown = found
    rs = RecScored(cand, None, cand.star)  # 위치 미지정 상세 조회 → distance_m=null
    rs.reasons = make_reasons(rs, Query(lat=cand.lat, lng=cand.lng))
    d = _item_dict(rs)
    d["score_breakdown"] = breakdown
    return d


@app.post("/restaurants/{rid}/reviews", response_model=ReviewOut, status_code=201)
def post_review(rid: str, body: ReviewIn, conn=Depends(get_conn)) -> dict:
    if get_scored(conn, rid) is None:  # 없는 가게·폐업 가게
        raise HTTPException(status_code=404, detail="restaurant not found")
    cur = conn.execute(
        "INSERT INTO user_reviews(restaurant_id,stars,text,tags,created_at) VALUES(?,?,?,?,?)",
        (rid, body.stars, body.text, json.dumps(body.tags, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    rebuild_scores(conn, region_of(conn, rid))  # ponytail: 리뷰마다 시군구 재계산(수천 건, ms 단위). 트래픽 커지면 큐/주기 배치
    return {"id": cur.lastrowid, "final_star": get_scored(conn, rid)[0].star}


@app.post("/restaurants/{rid}/report", status_code=202)
def post_report(rid: str, body: ReportIn, conn=Depends(get_conn)) -> dict:
    _require(conn, rid)
    conn.execute(
        "INSERT INTO reports(restaurant_id,field,message,created_at) VALUES(?,?,?,?)",
        (rid, body.field, body.message, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return {"status": "accepted"}
