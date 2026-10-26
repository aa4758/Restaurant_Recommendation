"""릴스형 추천 화면 API: exclude_ids, 리뷰 시트(GET reviews), 반응(POST /reactions), 레이트리밋, evidence."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load
from app.ratelimit import WRITE_LIMIT_PER_MIN, RateLimiter

CITY_HALL = {"lat": 37.5663, "lng": 126.9779}
DEV = "device-abc_123"


@pytest.fixture()
def dbp(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(p))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(p)
    return p


@pytest.fixture()
def client(dbp):
    from app.main import app
    return TestClient(app)


def _ids(r):
    return [it["id"] for it in r.json()["items"]]


# --- /recommend ----------------------------------------------------------
def test_recommend_limit_max_5(client):
    assert len(client.post("/recommend", json={**CITY_HALL, "limit": 5}).json()["items"]) == 5
    assert client.post("/recommend", json={**CITY_HALL, "limit": 6}).status_code == 422


def test_recommend_exclude_ids_reselects(client):
    base = _ids(client.post("/recommend", json=CITY_HALL))
    r = client.post("/recommend", json={**CITY_HALL, "exclude_ids": base[:2]})
    ids = _ids(r)
    assert len(ids) == 3 and not set(base[:2]) & set(ids)
    assert base[2] in ids  # 남은 후보는 기존 선정 그대로 유지
    # 없는 id 는 무시, 빈 목록은 기존과 동일
    assert _ids(client.post("/recommend", json={**CITY_HALL, "exclude_ids": ["NOPE"]})) == base
    assert _ids(client.post("/recommend", json={**CITY_HALL, "exclude_ids": []})) == base


def test_recommend_exclude_ids_max_200(client):
    assert client.post("/recommend", json={**CITY_HALL, "exclude_ids": [f"X{i}" for i in range(200)]}).status_code == 200
    assert client.post("/recommend", json={**CITY_HALL, "exclude_ids": [f"X{i}" for i in range(201)]}).status_code == 422


def test_recommend_item_evidence(client):
    for it in client.post("/recommend", json={**CITY_HALL, "limit": 5}).json()["items"]:
        assert it["evidence"] in {"low", "mid", "high"}
        assert it["evidence"] == client.get(f"/restaurants/{it['id']}").json()["score_breakdown"]["evidence"]


# --- GET /restaurants/{id}/reviews ---------------------------------------
def _insert(dbp, rows):
    c = sqlite3.connect(dbp)
    c.executemany(
        "INSERT INTO user_reviews(id,restaurant_id,stars,text,tags,user_id,created_at) VALUES(?,?,?,?,?,?,?)", rows)
    c.commit(); c.close()


def test_reviews_order_ad_flag_and_privacy(client, dbp):
    _insert(dbp, [
        (101, "R002", 4.0, "체험단으로 제공받아 작성", '["맛"]', "secret-dev-1", "2026-10-03T00:00:00+00:00"),
        (102, "R002", 3.0, "협찬 아님, 내돈내산", "[]", "secret-dev-2", "2026-10-01T00:00:00+00:00"),
        (103, "R002", 5.0, "맛있어요", '["친절"]', "secret-dev-3", "2026-10-02T00:00:00+00:00"),
        (104, "R002", 2.0, None, None, None, "2026-10-02T00:00:00+00:00"),
        (105, "R003", 2.0, "다른 가게", "[]", None, "2026-10-05T00:00:00+00:00"),
    ])
    r = client.get("/restaurants/R002/reviews")
    assert r.status_code == 200
    body = r.json()
    assert [it["id"] for it in body["items"]] == [104, 103, 102, 101]  # 광고 아님 → 최신 → 동일 시각 id 내림차순
    assert [it["ad_disclosed"] for it in body["items"]] == [False, False, False, True]  # 부정 표현은 광고 아님
    assert body["next_cursor"] is None
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id[101]["text"] == "체험단으로 제공받아 작성" and by_id[101]["tags"] == ["맛"]
    assert by_id[104]["text"] == "" and by_id[104]["tags"] == []
    for it in body["items"]:
        assert set(it) == {"id", "stars", "text", "tags", "created_at", "ad_disclosed"}
    assert "secret-dev" not in r.text


def test_reviews_cursor_pagination_stable(client, dbp):
    same = "2026-10-10T00:00:00+00:00"
    _insert(dbp, [(200 + i, "R004", 4.0, "협찬" if i % 4 == 0 else f"r{i}", "[]", None,
                   same if i < 6 else f"2026-10-{i:02d}T00:00:00+00:00") for i in range(13)])
    full = [it["id"] for it in client.get("/restaurants/R004/reviews?limit=50").json()["items"]]
    assert len(full) == 13
    got, cur = [], None
    while True:
        r = client.get("/restaurants/R004/reviews", params={"limit": 4, **({"cursor": cur} if cur else {})}).json()
        got += [it["id"] for it in r["items"]]
        cur = r["next_cursor"]
        if not cur:
            break
    assert got == full and len(set(got)) == 13
    # 커서 이후 새 리뷰가 추가돼도 기존 커서 이후 결과에 중복 없음
    first = client.get("/restaurants/R004/reviews", params={"limit": 4}).json()
    _insert(dbp, [(300, "R004", 4.0, "new", "[]", None, "2026-10-30T00:00:00+00:00")])
    nxt = client.get("/restaurants/R004/reviews", params={"limit": 50, "cursor": first["next_cursor"]}).json()
    assert not {it["id"] for it in first["items"]} & {it["id"] for it in nxt["items"]}


def test_reviews_validation_and_404(client):
    assert client.get("/restaurants/R001/reviews").json() == {"items": [], "next_cursor": None}
    assert client.get("/restaurants/NOPE/reviews").status_code == 404
    assert client.get("/restaurants/R001/reviews?limit=0").status_code == 422
    assert client.get("/restaurants/R001/reviews?limit=51").status_code == 422
    assert client.get("/restaurants/R001/reviews?limit=50").status_code == 200
    assert client.get("/restaurants/R001/reviews?cursor=%%%").status_code == 400


def test_posted_review_appears_in_sheet(client):
    client.post("/restaurants/R006/reviews", json={"stars": 4.5, "text": "굿", "tags": ["가성비"]})
    items = client.get("/restaurants/R006/reviews").json()["items"]
    assert len(items) == 1 and items[0]["stars"] == 4.5 and items[0]["tags"] == ["가성비"]


# --- POST /reactions -----------------------------------------------------
def _rows(dbp):
    c = sqlite3.connect(dbp)
    out = c.execute("SELECT device_id, restaurant_id, value, reason FROM reactions ORDER BY restaurant_id").fetchall()
    c.close()
    return out


def test_reactions_upsert_and_delete(client, dbp):
    assert client.post("/reactions", json={"device_id": DEV, "restaurant_id": "R001", "value": "like"}).status_code == 204
    r = client.post("/reactions", json={"device_id": DEV, "restaurant_id": "R001", "value": "dislike", "reason": "far"})
    assert r.status_code == 204 and r.content == b""
    assert _rows(dbp) == [(DEV, "R001", "dislike", "far")]  # 기기·가게당 1행 덮어쓰기
    client.post("/reactions", json={"device_id": DEV, "restaurant_id": "R001", "value": "dislike"})
    assert _rows(dbp) == [(DEV, "R001", "dislike", None)]
    assert client.post("/reactions", json={"device_id": DEV, "restaurant_id": "R001", "value": "none"}).status_code == 204
    assert _rows(dbp) == []
    assert client.post("/reactions", json={"device_id": DEV, "restaurant_id": "R001", "value": "none"}).status_code == 204


@pytest.mark.parametrize("body", [
    {"device_id": "short", "restaurant_id": "R001", "value": "like"},
    {"device_id": "a" * 65, "restaurant_id": "R001", "value": "like"},
    {"device_id": "bad id!!", "restaurant_id": "R001", "value": "like"},
    {"device_id": DEV, "restaurant_id": "R001", "value": "love"},
    {"device_id": DEV, "restaurant_id": "R001", "value": "like", "reason": "far"},
    {"device_id": DEV, "restaurant_id": "R001", "value": "none", "reason": "far"},
    {"device_id": DEV, "restaurant_id": "R001", "value": "dislike", "reason": "ugly"},
])
def test_reactions_validation(client, body):
    assert client.post("/reactions", json=body).status_code == 422


def test_reactions_device_id_bounds(client):
    for d in ("a" * 8, "A-z_09" + "x" * 58):
        assert client.post("/reactions", json={"device_id": d, "restaurant_id": "R001", "value": "like"}).status_code == 204


def test_reactions_404(client):
    assert client.post("/reactions", json={"device_id": DEV, "restaurant_id": "NOPE", "value": "like"}).status_code == 404


def test_reactions_do_not_affect_score_or_rank(client):
    reqs = [CITY_HALL, {**CITY_HALL, "limit": 5}, {**CITY_HALL, "genre": ["한식"]}]
    before = [client.post("/recommend", json=q).json() for q in reqs]
    ids = {it["id"] for b in before for it in b["items"]}
    details = {i: client.get(f"/restaurants/{i}").json() for i in ids}
    for n, i in enumerate(sorted(ids)):
        for k in range(5):  # 여러 기기가 몰아서 싫어요/좋아요
            client.post("/reactions", json={"device_id": f"device-{k:04d}", "restaurant_id": i,
                                            "value": "dislike" if n % 2 else "like",
                                            **({"reason": "not_into"} if n % 2 else {})})
    assert [client.post("/recommend", json=q).json() for q in reqs] == before
    assert {i: client.get(f"/restaurants/{i}").json() for i in ids} == details


# --- 레이트리밋 ----------------------------------------------------------
def test_rate_limiter_window():
    rl = RateLimiter(limit=2, window_s=60)
    assert rl.allow(["a"], now=0) and rl.allow(["a"], now=1)
    assert not rl.allow(["a"], now=2)
    assert rl.allow(["b"], now=2)  # 키별 독립
    assert rl.allow(["a"], now=60.5)  # 창 지나면 회복


def test_reactions_rate_limited(client):
    body = {"device_id": DEV, "restaurant_id": "R001", "value": "like"}
    codes = [client.post("/reactions", json=body).status_code for _ in range(WRITE_LIMIT_PER_MIN + 1)]
    assert codes[:-1] == [204] * WRITE_LIMIT_PER_MIN and codes[-1] == 429


def test_review_write_rate_limited(client):
    codes = [client.post("/restaurants/R007/reviews", json={"stars": 3}).status_code
             for _ in range(WRITE_LIMIT_PER_MIN + 1)]
    assert codes[:-1] == [201] * WRITE_LIMIT_PER_MIN and codes[-1] == 429
    assert client.get("/restaurants/R007/reviews").status_code == 200  # 읽기는 제한 없음


def test_existing_db_gets_reactions_table(tmp_path):
    from app import db as dbm
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE restaurants (id TEXT PRIMARY KEY, name TEXT NOT NULL, genre TEXT NOT NULL,"
              " moods TEXT NOT NULL DEFAULT '', lat REAL NOT NULL, lng REAL NOT NULL, status TEXT NOT NULL DEFAULT 'open',"
              " sigungu_code TEXT)")
    c.execute("CREATE TABLE user_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, restaurant_id TEXT NOT NULL,"
              " stars REAL NOT NULL, text TEXT, tags TEXT, user_id TEXT, verified INTEGER NOT NULL DEFAULT 0,"
              " created_at TEXT NOT NULL)")
    c.commit(); c.close()
    conn = dbm.connect(p)
    dbm.init_schema(conn)
    dbm.init_schema(conn)  # 멱등
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reactions)")}
    assert cols == {"device_id", "restaurant_id", "value", "reason", "updated_at"}
