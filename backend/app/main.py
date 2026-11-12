"""찐맛(JJINMAT) 백엔드 API. 계약: docs/01_planning_decision.md 'API 계약'."""
from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query as Q, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.auth import current_user, router as auth_router
from app.db import get_conn
from app.constants import ALCOHOL, GENRES, MOODS, PRICE_BANDS
from app.nlparse import parse
from app.schemas import (
    Item,
    ParseIn,
    ParseOut,
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
from app.ratelimit import IP_LIMIT_PER_MIN, WRITE_LIMIT_PER_MIN, write_limiter
from app import reviews
from app.scoring.prior import CENTURY_LABEL
from app.scoring.recommend import DISTANCE_RELAX_FACTOR, Query, Scored as RecScored, make_reasons, recommend
from app.service import candidates_near, get_scored, peer_percent, peers, rebuild_scores, region_of
from app.subtype import SUBTYPES

app = FastAPI(title="JJINMAT API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)




def today() -> date:
    return date.today()


def _item_dict(s: RecScored) -> dict:
    c = s.cand
    return {
        "id": c.id,
        "name": c.name,
        "genre": c.genre,
        "subtype": c.subtype,
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
        "relaxed": s.relaxed,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/meta/filters")
def meta_filters() -> dict:
    return {"price": PRICE_BANDS, "genre": GENRES, "subtype": SUBTYPES, "mood": MOODS, "alcohol": ALCOHOL}


@app.post("/filters/parse", response_model=ParseOut)
def post_filters_parse(body: ParseIn, conn=Depends(get_conn)) -> dict:
    """자연어 조건 → 필터(규칙 기반). 미인식 낱말만 집계, 원문은 저장하지 않음."""
    return parse(body.text, conn)


@app.post("/recommend", response_model=RecommendResponse)
def post_recommend(req: RecommendRequest, conn=Depends(get_conn), day: date = Depends(today)) -> dict:
    q = Query(**req.model_dump(exclude={"exclude_ids"}))
    # 완화 시 반경이 DISTANCE_RELAX_FACTOR 배까지 늘어나므로 그만큼 조회
    cands = candidates_near(conn, q.lat, q.lng, q.radius_m * DISTANCE_RELAX_FACTOR)
    if req.exclude_ids:  # 싫어요 숨김: 후보에서 먼저 빼고 기존 선정·완화·로테이션 그대로
        excl = set(req.exclude_ids)
        cands = [c for c in cands if c.id not in excl]
    items, relaxed, total = recommend(cands, q, day=day, with_total=True)
    return {"items": [_with_peer(conn, _item_dict(s)) for s in items], "relaxed": relaxed, "total": total}


def _with_peer(conn, d: dict) -> dict:
    p = peer_percent(conn, d["id"])
    if p:
        d["food"], d["food_percentile"] = p
    return d


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
    d = _with_peer(conn, _item_dict(rs))
    d["score_breakdown"] = breakdown
    d["designations"] = cand.designations + ([CENTURY_LABEL] if cand.century_store else [])
    return d


def _client_ip(request: Request) -> str:
    """연결 상대 IP. 프록시 뒤라면 uvicorn --proxy-headers --forwarded-allow-ips(LB 대역)로만 XFF 신뢰."""
    return request.client.host if request.client else "unknown"


def _rate_limit(scope: str, request: Request, device_id: str | None) -> None:
    """기기 키 우선(분당 WRITE_LIMIT_PER_MIN) + IP 버킷(분당 IP_LIMIT_PER_MIN, NAT 공유 감안)."""
    keys: list[tuple[str, int]] = [(f"{scope}:ip:{_client_ip(request)}", IP_LIMIT_PER_MIN)]
    if device_id:
        keys.insert(0, (f"{scope}:dev:{device_id}", WRITE_LIMIT_PER_MIN))
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


_REVIEW_COLS = "SELECT id, stars, text, tags, created_at, ad_disclosed, onsite, updated_at FROM user_reviews"
_REVIEW_ORDER = " ORDER BY ad_disclosed ASC, created_at DESC, id DESC LIMIT ?"


@app.get("/restaurants/{rid}/reviews", response_model=ReviewPage)
def get_reviews(
    rid: str, limit: int = Q(default=20, ge=1, le=50), cursor: str | None = None, conn=Depends(get_conn)
) -> dict:
    """읽기 전용 리뷰 시트. 별점 있는 리뷰만, 계정 ID(user_id) 등은 노출하지 않음.

    정렬: 광고 표시 아님 먼저 → created_at 내림차순 → id 내림차순. 저장된 ad_disclosed 로 SQL 키셋 페이지네이션
    (인덱스 idx_reviews_sheet). 커서 = base64([ad, created_at, id]) — 기존 형식 그대로.
    """
    _require(conn, rid)
    db.backfill_ad_disclosed(conn)  # API 외 경로로 들어온 미계산 행(부분 인덱스, 보통 0건)
    where = " WHERE restaurant_id = ? AND stars IS NOT NULL AND stars > 0"
    args: list = [rid]
    if cursor:
        c_ad, c_ca, c_id = _decode_cursor(cursor)
        where += " AND (ad_disclosed > ? OR (ad_disclosed = ? AND (created_at < ? OR (created_at = ? AND id < ?))))"
        args += [c_ad, c_ad, c_ca, c_ca, c_id]
    rows = conn.execute(_REVIEW_COLS + where + _REVIEW_ORDER, (*args, limit + 1)).fetchall()
    page = rows[:limit]
    items = [
        ReviewItem(
            id=r["id"], stars=float(r["stars"]), text=r["text"] or "",
            tags=json.loads(r["tags"]) if r["tags"] else [], created_at=r["created_at"],
            ad_disclosed=bool(r["ad_disclosed"]), onsite=bool(r["onsite"]), edited=r["updated_at"] is not None,
        ).model_dump()
        for r in page
    ]
    last = page[-1] if page else None
    nxt = _encode_cursor(bool(last["ad_disclosed"]), last["created_at"], int(last["id"])) if len(rows) > limit else None
    return {"items": items, "next_cursor": nxt}


@app.post("/reactions", status_code=204)
def post_reaction(body: ReactionIn, request: Request, conn=Depends(get_conn)) -> Response:
    """좋아요/싫어요 기록(개인화 전용). 점수·순위 계산에는 절대 사용하지 않음."""
    _rate_limit("reaction", request, body.device_id)
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
def post_review(rid: str, body: ReviewIn, request: Request, uid: int = Depends(current_user),
                conn=Depends(get_conn)) -> dict:
    """계정·가게당 1개(있으면 덮어씀). docs/01 R-0~R-6."""
    _rate_limit("review", request, f"u{uid}")  # 계정 키 + IP (docs/01 L-5: 리뷰는 로그인 필수)
    if get_scored(conn, rid) is None:  # 없는 가게·폐업 가게
        raise HTTPException(status_code=404, detail="restaurant not found")
    out = reviews.write_review(conn, uid, rid, body)
    rebuild_scores(conn, region_of(conn, rid))  # ponytail: 리뷰마다 시군구 재계산(수천 건, ms 단위). 트래픽 커지면 큐/주기 배치
    return {**out, "final_star": get_scored(conn, rid)[0].star}


@app.delete("/restaurants/{rid}/reviews/me", status_code=204)
def delete_my_review(rid: str, request: Request, uid: int = Depends(current_user), conn=Depends(get_conn)) -> Response:
    _rate_limit("review", request, f"u{uid}")
    reviews.delete_review(conn, uid, rid)
    rebuild_scores(conn, region_of(conn, rid))
    return Response(status_code=204)


@app.get("/restaurants/{rid}/menus")
def get_menus(rid: str, conn=Depends(get_conn)) -> dict:
    """리뷰 메뉴 입력 자동완성(R-4): 그 가게의 알려진 메뉴(지정목록·확정 메뉴 등)."""
    _require(conn, rid)
    rows = conn.execute("SELECT name, MAX(price) AS price FROM menus WHERE restaurant_id=? GROUP BY name"
                        " ORDER BY is_signature DESC, name LIMIT 30", (rid,)).fetchall()
    return {"items": [{"name": r["name"], "price": r["price"]} for r in rows]}


@app.get("/restaurants/{rid}/peers")
def get_peers(rid: str, limit: int = Q(default=20, ge=1, le=50), offset: int = Q(default=0, ge=0, le=5000),
              conn=Depends(get_conn)) -> dict:
    """같은 시군구·같은 음식(세부 분류, 없으면 장르) 가게, 별점 내림차순(2026-11-12). 자기 자신 포함."""
    out = peers(conn, rid, limit, offset)
    if out is None:
        raise HTTPException(status_code=404, detail="restaurant not found")
    return out


@app.get("/me/reviews")
def get_my_reviews(uid: int = Depends(current_user), conn=Depends(get_conn)) -> dict:
    """내가 다녀온 가게 = 내 리뷰 목록(R-7)."""
    return {"items": reviews.my_reviews(conn, uid)}


@app.post("/restaurants/{rid}/report", status_code=202)
def post_report(rid: str, body: ReportIn, conn=Depends(get_conn)) -> dict:
    _require(conn, rid)
    conn.execute(
        "INSERT INTO reports(restaurant_id,field,message,created_at) VALUES(?,?,?,?)",
        (rid, body.field, body.message, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return {"status": "accepted"}
