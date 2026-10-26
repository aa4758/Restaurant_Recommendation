"""찐맛(JJINMAT) 백엔드 API. 계약: docs/01_planning_decision.md 'API 계약'."""
from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query as Q, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.constants import ALCOHOL, GENRES, MOODS, PRICE_BANDS
from app.schemas import (
    Item,
    RecommendRequest,
    RecommendResponse,
    ReactionIn,
    ReportIn,
    RestaurantDetail,
    ReviewIn,
    ReviewItem,
    ReviewOut,
    ReviewPage,
)
from app.ratelimit import write_limiter
from app.scoring.prior import is_ad_text
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
        "address": c.address,
        "evidence": c.evidence,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/meta/filters")
def meta_filters() -> dict:
    return {"price": PRICE_BANDS, "genre": GENRES, "mood": MOODS, "alcohol": ALCOHOL}


@app.post("/recommend", response_model=RecommendResponse)
def post_recommend(req: RecommendRequest, conn=Depends(get_conn), day: date = Depends(today)) -> dict:
    q = Query(**req.model_dump(exclude={"exclude_ids"}))
    # 완화 시 반경이 DISTANCE_RELAX_FACTOR 배까지 늘어나므로 그만큼 조회
    cands = candidates_near(conn, q.lat, q.lng, q.radius_m * DISTANCE_RELAX_FACTOR)
    if req.exclude_ids:  # 싫어요 숨김: 후보에서 먼저 빼고 기존 선정·완화·로테이션 그대로
        excl = set(req.exclude_ids)
        cands = [c for c in cands if c.id not in excl]
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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit(keys: list[str]) -> None:
    if not write_limiter.allow(keys):
        raise HTTPException(status_code=429, detail="too many requests")


def _encode_cursor(ad: bool, created_at: str, rid: int) -> str:
    raw = json.dumps([int(ad), created_at, rid], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cur: str) -> tuple[int, str, int]:
    try:
        raw = base64.urlsafe_b64decode(cur + "=" * (-len(cur) % 4))
        ad, created_at, rid = json.loads(raw)
        if not (isinstance(ad, int) and isinstance(created_at, str) and isinstance(rid, int)):
            raise ValueError
        return ad, created_at, rid
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor")


def _after(row: tuple[int, str, int], cur: tuple[int, str, int]) -> bool:
    """정렬(광고 아님 먼저 → created_at 내림차순 → id 내림차순)에서 row 가 커서 뒤인가."""
    ad, ca, i = row
    c_ad, c_ca, c_i = cur
    if ad != c_ad:
        return ad > c_ad
    if ca != c_ca:
        return ca < c_ca
    return i < c_i


@app.get("/restaurants/{rid}/reviews", response_model=ReviewPage)
def get_reviews(
    rid: str, limit: int = Q(default=20, ge=1, le=50), cursor: str | None = None, conn=Depends(get_conn)
) -> dict:
    """읽기 전용 리뷰 시트. 별점 있는 리뷰만, 기기 ID(user_id) 등은 노출하지 않음."""
    _require(conn, rid)
    cur = _decode_cursor(cursor) if cursor else None
    # 광고 표시 판별은 본문 정규식(prior.is_ad_text, 부정 표현 제외) → SQL 정렬 불가, 가게 단위로 메모리 정렬
    # ponytail: 가게당 리뷰 수천 건까지 ms 단위. 커지면 ad_disclosed 컬럼 저장 후 SQL 키셋 페이지네이션
    rows = conn.execute(
        "SELECT id, stars, text, tags, created_at FROM user_reviews"
        " WHERE restaurant_id = ? AND stars IS NOT NULL AND stars > 0",
        (rid,),
    ).fetchall()
    keyed = [((int(is_ad_text(r["text"])), r["created_at"], int(r["id"])), r) for r in rows]
    keyed.sort(key=lambda kr: (kr[0][1], kr[0][2]), reverse=True)  # 최신순, 동일 시각은 id 내림차순
    keyed.sort(key=lambda kr: kr[0][0])  # 안정 정렬: 광고 아님 먼저
    if cur:
        keyed = [kr for kr in keyed if _after(kr[0], cur)]
    page = keyed[:limit]
    items = [
        ReviewItem(
            id=r["id"], stars=float(r["stars"]), text=r["text"] or "",
            tags=json.loads(r["tags"]) if r["tags"] else [], created_at=r["created_at"], ad_disclosed=bool(k[0]),
        ).model_dump()
        for k, r in page
    ]
    nxt = _encode_cursor(bool(page[-1][0][0]), *page[-1][0][1:]) if len(keyed) > limit else None
    return {"items": items, "next_cursor": nxt}


@app.post("/reactions", status_code=204)
def post_reaction(body: ReactionIn, request: Request, conn=Depends(get_conn)) -> Response:
    """좋아요/싫어요 기록(개인화 전용). 점수·순위 계산에는 절대 사용하지 않음."""
    _rate_limit([f"reaction:dev:{body.device_id}", f"reaction:ip:{_client_ip(request)}"])
    _require(conn, body.restaurant_id)
    if body.value == "none":
        conn.execute("DELETE FROM reactions WHERE device_id=? AND restaurant_id=?", (body.device_id, body.restaurant_id))
    else:
        conn.execute(
            "INSERT INTO reactions(device_id,restaurant_id,value,reason,updated_at) VALUES(?,?,?,?,?)"
            " ON CONFLICT(device_id,restaurant_id) DO UPDATE SET value=excluded.value, reason=excluded.reason,"
            " updated_at=excluded.updated_at",
            (body.device_id, body.restaurant_id, body.value, body.reason, datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()
    return Response(status_code=204)


@app.post("/restaurants/{rid}/reviews", response_model=ReviewOut, status_code=201)
def post_review(rid: str, body: ReviewIn, request: Request, conn=Depends(get_conn)) -> dict:
    _rate_limit([f"review:ip:{_client_ip(request)}"])
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
