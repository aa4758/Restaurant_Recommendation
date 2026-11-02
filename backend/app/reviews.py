"""리뷰 작성·수정·삭제와 리뷰 집계(메뉴 확정·가격대·분위기). 결정: docs/01 '리뷰 개편 세부' R-1~R-7."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median

from fastapi import HTTPException

from app.constants import MOODS, PRICE_BANDS
from app.scoring.prior import is_ad_text
from app.scoring.recommend import haversine_m

ONSITE_M = 200
MAX_ACCURACY_M = 100  # GPS 오차 허용 상한
NEW_ACCOUNT_DAYS = 7
NEW_PER_DAY, NEW_TOTAL, PER_DAY = 3, 10, 20
MIN_AGG = 3  # 가격대·분위기 집계 최소 응답 리뷰 수
MENU_CONFIRM = 2  # 서로 다른 계정 수


def _now() -> datetime:
    return datetime.now(timezone.utc)


def norm_menu(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def is_onsite(conn: sqlite3.Connection, rid: str, positions: list) -> bool:
    lat, lng = conn.execute("SELECT lat, lng FROM restaurants WHERE id=?", (rid,)).fetchone()
    return any(haversine_m(p.lat, p.lng, lat, lng) - min(p.accuracy or 0, MAX_ACCURACY_M) <= ONSITE_M for p in positions)


def _check_limits(conn: sqlite3.Connection, uid: int) -> None:
    """새 리뷰만 셈(수정 제외). 초과면 429 + 앱에 그대로 보여 줄 한국어 문구."""
    now = _now()
    joined = datetime.fromisoformat(conn.execute("SELECT created_at FROM users WHERE id=?", (uid,)).fetchone()[0])
    since = (now - timedelta(days=1)).isoformat()
    day = conn.execute("SELECT COUNT(*) FROM user_reviews WHERE user_id=? AND created_at >= ?", (str(uid), since)).fetchone()[0]
    if now - joined < timedelta(days=NEW_ACCOUNT_DAYS):
        total = conn.execute("SELECT COUNT(*) FROM user_reviews WHERE user_id=?", (str(uid),)).fetchone()[0]
        if day >= NEW_PER_DAY or total >= NEW_TOTAL:
            raise HTTPException(429, f"가입 후 {NEW_ACCOUNT_DAYS}일 동안은 하루 {NEW_PER_DAY}개, 모두 {NEW_TOTAL}개까지 쓸 수 있어요.")
    elif day >= PER_DAY:
        raise HTTPException(429, f"리뷰는 하루 {PER_DAY}개까지 쓸 수 있어요.")


def write_review(conn: sqlite3.Connection, uid: int, rid: str, body) -> dict:
    """계정·가게당 1개: 있으면 덮어씀(R-1). 현장 작성은 한 번 붙으면 유지(R-2a)."""
    now = _now().isoformat()
    onsite = is_onsite(conn, rid, body.positions)
    tags = json.dumps(body.tags, ensure_ascii=False)
    moods = json.dumps(body.moods, ensure_ascii=False) if body.moods else None
    old = conn.execute("SELECT id, onsite FROM user_reviews WHERE user_id=? AND restaurant_id=?", (str(uid), rid)).fetchone()
    if old:
        review_id, onsite = old["id"], bool(old["onsite"]) or onsite
        conn.execute("UPDATE user_reviews SET stars=?, text=?, tags=?, ad_disclosed=?, updated_at=?, onsite=?, spend=?, moods=?"
                     " WHERE id=?", (body.stars, body.text, tags, int(is_ad_text(body.text)), now, int(onsite),
                                     body.spend, moods, review_id))
        conn.execute("DELETE FROM review_menus WHERE review_id=?", (review_id,))
    else:
        _check_limits(conn, uid)
        review_id = conn.execute(
            "INSERT INTO user_reviews(restaurant_id,stars,text,tags,user_id,ad_disclosed,created_at,onsite,spend,moods)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rid, body.stars, body.text, tags, str(uid), int(is_ad_text(body.text)), now, int(onsite), body.spend, moods),
        ).lastrowid
    conn.executemany("INSERT INTO review_menus(review_id,name,norm,price) VALUES(?,?,?,?)",
                     [(review_id, m.name.strip(), norm_menu(m.name), m.price) for m in body.menus])
    aggregate(conn, rid)
    conn.commit()
    return {"id": review_id, "updated": old is not None, "onsite": onsite}


def delete_review(conn: sqlite3.Connection, uid: int, rid: str) -> None:
    row = conn.execute("SELECT id FROM user_reviews WHERE user_id=? AND restaurant_id=?", (str(uid), rid)).fetchone()
    if row is None:
        raise HTTPException(404, "review not found")
    last = conn.execute("SELECT deleted_at FROM review_deletions WHERE user_id=? AND restaurant_id=?", (str(uid), rid)).fetchone()
    if last and _now() - datetime.fromisoformat(last[0]) < timedelta(days=1):
        raise HTTPException(429, "같은 가게 리뷰는 하루에 한 번만 지울 수 있어요.")
    conn.execute("DELETE FROM user_reviews WHERE id=?", (row["id"],))  # review_menus 는 CASCADE
    conn.execute("INSERT INTO review_deletions(user_id,restaurant_id,deleted_at) VALUES(?,?,?)"
                 " ON CONFLICT(user_id,restaurant_id) DO UPDATE SET deleted_at=excluded.deleted_at",
                 (str(uid), rid, _now().isoformat()))
    aggregate(conn, rid)
    conn.commit()


def _robust_median(prices: list[int]) -> int | None:
    if not prices:
        return None
    m = median(prices)
    kept = [p for p in prices if m / 2 <= p <= m * 2]
    return round(median(kept))


def aggregate(conn: sqlite3.Connection, rid: str) -> None:
    """리뷰 → 확정 메뉴(R-4a)·가격대(R-5)·분위기(R-6). 리뷰가 바뀔 때마다 그 가게만 다시 계산."""
    # 메뉴: 서로 다른 계정 MENU_CONFIRM 이상
    rows = conn.execute("SELECT m.name, m.norm, m.price, u.user_id FROM review_menus m JOIN user_reviews u ON u.id=m.review_id"
                        " WHERE u.restaurant_id=?", (rid,)).fetchall()
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["norm"], []).append(r)
    conn.execute("DELETE FROM menus WHERE restaurant_id=? AND source='user'", (rid,))
    now = _now().isoformat()
    for g in groups.values():
        if len({r["user_id"] for r in g}) >= MENU_CONFIRM:
            name = Counter(r["name"] for r in g).most_common(1)[0][0]
            price = _robust_median([r["price"] for r in g if r["price"]])
            conn.execute("INSERT INTO menus(restaurant_id,name,price,source,updated_at) VALUES(?,?,?,'user',?)",
                         (rid, name, price, now))
    # 가격대: 응답 MIN_AGG 이상이면 최빈값(동률이면 낮은 구간)
    spends = [r[0] for r in conn.execute("SELECT spend FROM user_reviews WHERE restaurant_id=? AND spend IS NOT NULL", (rid,))]
    if len(spends) >= MIN_AGG:
        c = Counter(spends)
        band = max(PRICE_BANDS, key=lambda b: (c[b], -PRICE_BANDS.index(b)))
        conn.execute("UPDATE restaurants SET price_band=?, price_src='review' WHERE id=?", (band, rid))
    else:
        conn.execute("UPDATE restaurants SET price_band=NULL, price_src=NULL WHERE id=? AND price_src='review'", (rid,))
    # 분위기: 응답 MIN_AGG 이상 + 절반 이상 고른 것
    answers = [json.loads(r[0]) for r in conn.execute(
        "SELECT moods FROM user_reviews WHERE restaurant_id=? AND moods IS NOT NULL", (rid,))]
    if len(answers) >= MIN_AGG:
        c = Counter(m for a in answers for m in set(a))
        picked = [m for m in MOODS if c[m] * 2 >= len(answers)]
        conn.execute("UPDATE restaurants SET moods=?, moods_src='review' WHERE id=?", ("|".join(picked), rid))
    else:
        conn.execute("UPDATE restaurants SET moods='', moods_src=NULL WHERE id=? AND moods_src='review'", (rid,))


def my_reviews(conn: sqlite3.Connection, uid: int) -> list[dict]:
    rows = conn.execute(
        "SELECT u.id, u.restaurant_id, r.name, u.stars, u.text, u.tags, u.spend, u.moods, u.onsite, u.created_at, u.updated_at"
        " FROM user_reviews u JOIN restaurants r ON r.id=u.restaurant_id WHERE u.user_id=?"
        " ORDER BY COALESCE(u.updated_at, u.created_at) DESC", (str(uid),)).fetchall()
    menus: dict[int, list] = {}
    for m in conn.execute("SELECT review_id, name, price FROM review_menus WHERE review_id IN"
                          " (SELECT id FROM user_reviews WHERE user_id=?)", (str(uid),)):
        menus.setdefault(m["review_id"], []).append({"name": m["name"], "price": m["price"]})
    return [{
        "restaurant_id": r["restaurant_id"], "name": r["name"], "stars": float(r["stars"]), "text": r["text"] or "",
        "tags": json.loads(r["tags"]) if r["tags"] else [], "spend": r["spend"],
        "moods": json.loads(r["moods"]) if r["moods"] else [], "menus": menus.get(r["id"], []),
        "onsite": bool(r["onsite"]), "created_at": r["created_at"], "updated_at": r["updated_at"],
    } for r in rows]
