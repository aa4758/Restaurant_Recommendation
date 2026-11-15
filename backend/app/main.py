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
    LikesIn,
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


@app.on_event("startup")
def _warm_places() -> None:
    """지명 색인(nlparse._places, 전체 스캔 수 초)을 첫 검색 전에 백그라운드로 만들어 둠."""
    import threading

    from app.db import connect
    from app.nlparse import _db_file, _places

    def run():
        c = connect()
        try:
            _places(_db_file(c))
        finally:
            c.close()

    threading.Thread(target=run, daemon=True).start()




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
    q = Query(**req.model_dump(exclude={"exclude_ids", "name", "name_only"}))
    excl = set(req.exclude_ids)
    named = _name_matches(conn, req, q, excl)  # 이름 맞는 가게(가까운 순) → 맨 앞, 이어서 평소 추천
    head = named[req.offset: req.offset + req.limit]
    if named and req.name_only:
        return {"items": head, "relaxed": [], "total": len(named)}
    # 완화 시 반경이 DISTANCE_RELAX_FACTOR 배까지 늘어나므로 그만큼 조회
    cands = candidates_near(conn, q.lat, q.lng, q.radius_m * DISTANCE_RELAX_FACTOR)
    skip = excl | {d["id"] for d in named}
    if skip:  # 싫어요 숨김·이름 결과: 후보에서 먼저 빼고 기존 선정·완화·로테이션 그대로
        cands = [c for c in cands if c.id not in skip]
    q.offset = max(0, req.offset - len(named))
    items, relaxed, total = recommend(cands, q, day=day, with_total=True)
    rest = [_with_peer(conn, _item_dict(s)) for s in items[: req.limit - len(head)]]
    return {"items": head + rest, "relaxed": relaxed, "total": len(named) + total}


NAME_NEAREST = 10  # 이름 검색 결과 최대 개수(가까운 순). ponytail: 체인점은 가까운 10곳만 — 더 필요하면 이어 받기로
NAME_NEAR_M = 20000  # 이름 + 음식·지명으로 함께 읽힐 때 이름 결과 거리 한도


def _name_matches(conn, req: RecommendRequest, q: Query, excl: set) -> list[dict]:
    """가게 이름 검색(2026-11-15, docs/01 '가게 이름 검색'): 전국에서 이름 맞는 가게를 기준 위치에서 가까운 순으로. 조건 필터는 안 걸고 표시만."""
    from app.nlparse import _db_file, name_hits
    from app.scoring.recommend import haversine_m

    if not req.name:
        return []
    # 일치 단계(전체 → 앞부분 → 낱말) 다음 가까운 순
    hits = sorted((tier, haversine_m(q.lat, q.lng, lat, lng), rid)
                  for rid, lat, lng, tier in name_hits(_db_file(conn), req.name) if rid not in excl)
    if not req.name_only:  # 음식·지명으로도 읽힘 → 먼 동명 가게(부산의 '국밥')는 빼고 가까운 것만. 이름으로만 읽히면 전국
        hits = [h for h in hits if h[1] <= NAME_NEAR_M]
    out = []
    for _, dist, rid in hits[:NAME_NEAREST]:
        found = get_scored(conn, rid)
        if found is None:
            continue
        s = RecScored(found[0], dist, found[0].star)
        s.reasons = make_reasons(s, q)
        out.append({**_with_peer(conn, _item_dict(s)), "name_match": True})
    return out


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


@app.get("/me/likes")
def get_my_likes(uid: int = Depends(current_user), conn=Depends(get_conn)) -> dict:
    """좋아요 목록(docs/01 L-1), 최신순. 동은 지번 주소에서."""
    from app.nlparse import jibun_dong

    rows = conn.execute(
        "SELECT l.restaurant_id, r.name, r.sido, r.sigungu, r.address_jibun, COALESCE(r.subtype, r.genre) AS food, sc.star, l.created_at"
        " FROM user_likes l JOIN restaurants r ON r.id=l.restaurant_id LEFT JOIN scores sc ON sc.restaurant_id=l.restaurant_id"
        " WHERE l.user_id=? ORDER BY l.created_at DESC, l.rowid DESC", (uid,)).fetchall()
    return {"items": [{"restaurant_id": r["restaurant_id"], "name": r["name"], "sido": r["sido"], "sigungu": r["sigungu"],
                       "dong": jibun_dong(r["address_jibun"]), "food": r["food"], "star": r["star"], "created_at": r["created_at"]}
                      for r in rows]}


@app.post("/me/likes", status_code=204)
def post_my_likes(body: LikesIn, request: Request, uid: int = Depends(current_user), conn=Depends(get_conn)) -> Response:
    """좋아요 추가(로그인 직후 기기 좋아요 합치기 겸). 이미 있거나 없는 가게는 무시."""
    _rate_limit("like", request, f"user{uid}")  # 계정당 분당 30회
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO user_likes(user_id,restaurant_id,created_at) SELECT ?,id,? FROM restaurants WHERE id=?",
        [(uid, now, rid) for rid in dict.fromkeys(body.ids)])
    conn.commit()
    return Response(status_code=204)


@app.delete("/me/likes/{rid}", status_code=204)
def delete_my_like(rid: str, uid: int = Depends(current_user), conn=Depends(get_conn)) -> Response:
    conn.execute("DELETE FROM user_likes WHERE user_id=? AND restaurant_id=?", (uid, rid))
    conn.commit()
    return Response(status_code=204)


@app.post("/restaurants/{rid}/report", status_code=202)
def post_report(rid: str, body: ReportIn, conn=Depends(get_conn)) -> dict:
    _require(conn, rid)
    conn.execute(
        "INSERT INTO reports(restaurant_id,field,message,created_at) VALUES(?,?,?,?)",
        (rid, body.field, body.message, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return {"status": "accepted"}
