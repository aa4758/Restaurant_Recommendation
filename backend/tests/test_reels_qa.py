"""QA: 릴스형 추천 화면 백엔드 경계·회귀 검증 (품질검증팀).

스펙: docs/01_planning_decision.md '릴스형 추천 화면' + API 계약.
xfail = 확인된 결함(제품 코드 미수정, 보고만).
"""
import base64
import json
import sqlite3
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load
from app.ratelimit import IP_LIMIT_PER_MIN, WRITE_LIMIT_PER_MIN, RateLimiter, write_limiter
from app.scoring.recommend import Candidate, Query, recommend

CH = {"lat": 37.5663, "lng": 126.9779}
DEV = "qa-device-0001"


@pytest.fixture()
def dbp(tmp_path, monkeypatch):
    p = tmp_path / "qa.db"
    monkeypatch.setenv("JJINMAT_DB", str(p))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(p)
    return p


@pytest.fixture()
def client(dbp, login):
    from app.main import app
    c = TestClient(app)
    c.headers.update(login())
    yield c
    app.dependency_overrides.clear()


def _ids(r):
    assert r.status_code == 200, r.text
    return [it["id"] for it in r.json()["items"]]


def _react(client, rid, value, dev=DEV, **kw):
    return client.post("/reactions", json={"device_id": dev, "restaurant_id": rid, "value": value, **kw})


def _insert(dbp, rows):
    c = sqlite3.connect(dbp)
    c.executemany(
        "INSERT INTO user_reviews(id,restaurant_id,stars,text,tags,user_id,created_at) VALUES(?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()


def _walk(client, rid, limit):
    got, cur, pages = [], None, 0
    while True:
        r = client.get(f"/restaurants/{rid}/reviews", params={"limit": limit, **({"cursor": cur} if cur else {})})
        assert r.status_code == 200
        body = r.json()
        got += body["items"]
        pages += 1
        cur = body["next_cursor"]
        if not cur:
            return got, pages
        assert pages < 10_000


# --- 반응은 점수·순위·로테이션에 영향 없음 ------------------------------------
def test_reactions_do_not_change_rotation_over_days(client):
    from app.main import today
    days = [date(2026, 1, 1) + timedelta(days=d) for d in range(0, 21, 3)]

    def snap():
        out = []
        for d in days:
            client.app.dependency_overrides[today] = lambda d=d: d
            out.append(client.post("/recommend", json={**CH, "limit": 5, "radius_m": 3000}).json())
        return out

    before = snap()
    ids = {it["id"] for b in before for it in b["items"]}
    for k in range(4):
        for i in sorted(ids):
            write_limiter.reset()
            _react(client, i, "dislike" if k % 2 else "like", dev=f"qa-dev-{k:05d}",
                   **({"reason": "far"} if k % 2 else {}))
    assert snap() == before


def test_reactions_table_not_read_by_scoring(client, dbp):
    """reactions 행이 대량이어도 rebuild 후 점수 동일(개인화 전용)."""
    from app import db
    from app.service import rebuild_scores
    detail = client.get("/restaurants/R001").json()
    c = sqlite3.connect(dbp)
    c.executemany("INSERT INTO reactions VALUES(?,?,?,?,?)",
                  [(f"bulk-{i:06d}", "R001", "dislike", "not_into", "2026-10-01") for i in range(500)])
    c.commit(); c.close()
    conn = db.connect(dbp)
    rebuild_scores(conn)
    conn.close()
    after = client.get("/restaurants/R001").json()
    assert after["star"] == detail["star"] and after["percentile"] == detail["percentile"]


# --- exclude_ids ---------------------------------------------------------
def test_exclude_keeps_three_and_relaxes(client):
    q = {**CH, "radius_m": 300}
    base = client.post("/recommend", json=q).json()
    excl = [it["id"] for it in base["items"]]
    for _ in range(3):  # 반복 싫어요해도 후보가 있으면 계속 3곳
        r = client.post("/recommend", json={**q, "exclude_ids": excl}).json()
        assert len(r["items"]) == 3, r
        assert not set(excl) & {it["id"] for it in r["items"]}
        excl += [it["id"] for it in r["items"]]
    assert "distance" in r["relaxed"]  # 좁은 반경 → 제외로 모자라면 완화


def test_exclude_does_not_relax_when_not_needed(client):
    q = {**CH, "radius_m": 3000}
    base = client.post("/recommend", json=q).json()
    r = client.post("/recommend", json={**q, "exclude_ids": [base["items"][0]["id"]]}).json()
    assert r["relaxed"] == base["relaxed"] == []


def test_exclude_alcohol_never_relaxed(client):
    q = {**CH, "radius_m": 3000, "alcohol": "no"}
    nonalc = []
    for _ in range(20):
        r = client.post("/recommend", json={**q, "exclude_ids": nonalc}).json()
        assert all(not it["alcohol"] for it in r["items"])
        assert "alcohol" not in r["relaxed"]
        if not r["items"]:
            break
        nonalc += [it["id"] for it in r["items"]]


def test_exclude_everything_returns_empty_not_error(client):
    full = _ids(client.post("/recommend", json={**CH, "radius_m": 20000, "limit": 5}))
    all_ids = [f"R{i:03d}" for i in range(1, 200)]
    r = client.post("/recommend", json={**CH, "exclude_ids": all_ids})
    assert r.status_code == 200 and r.json()["items"] == []
    assert full


@pytest.mark.parametrize("body", [
    {"limit": 6}, {"limit": 0}, {"limit": 100},
    {"exclude_ids": ["x"] * 201},
    {"exclude_ids": ["x" * 65]},
    {"exclude_ids": "R001"},
    {"exclude_ids": [1, 2]},
])
def test_recommend_rejects(client, body):
    assert client.post("/recommend", json={**CH, **body}).status_code == 422


def test_exclude_duplicates_and_unknown_ok(client):
    base = _ids(client.post("/recommend", json=CH))
    r = _ids(client.post("/recommend", json={**CH, "exclude_ids": [base[0]] * 200}))
    assert base[0] not in r and len(r) == 3


def test_exclude_unshown_candidate_keeps_rotation():
    """화면에 없는 후보 하나를 숨겨도 보이는 3곳·순서는 그대로여야 함(제외 후 기존 로테이션 유지)."""
    cands = [Candidate(id=f"T{i:02d}", name=f"t{i}", genre="한식", price_band="1~2만", moods=[], alcohol=False,
                       lat=37.5663, lng=126.9779, star=4.0, percentile=10) for i in range(8)]
    q = Query(lat=37.5663, lng=126.9779)
    changed = 0
    for d in range(30):
        day = date(2026, 1, 1) + timedelta(days=d)
        top, _ = recommend(cands, q, day=day)
        top_ids = [s.cand.id for s in top]
        hidden = next(c.id for c in cands if c.id not in top_ids)
        top2, _ = recommend([c for c in cands if c.id != hidden], q, day=day)
        changed += [s.cand.id for s in top2] != top_ids
    assert changed == 0, f"숨김 1건으로 {changed}/30일 순서·구성이 바뀜"


# --- device_id / reason / none -------------------------------------------
@pytest.mark.parametrize("dev", ["abcdefgh\n", " abcdefgh", "abcdefg", "가나다라마바사아", "abc.defgh", "a" * 65, ""])
def test_device_id_rejected(client, dev):
    assert _react(client, "R001", "like", dev=dev).status_code == 422


def test_reason_rules(client, dbp):
    for v in ("like", "none"):
        for rs in ("far", "price", "not_into", "visited"):
            assert _react(client, "R001", v, reason=rs).status_code == 422
    assert _react(client, "R001", "dislike", reason=None).status_code == 204
    for rs in ("far", "price", "not_into", "visited"):
        assert _react(client, "R001", "dislike", reason=rs).status_code == 204
    # dislike(reason) → like 덮어쓰면 reason 지워짐
    assert _react(client, "R001", "like").status_code == 204
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT value, reason FROM reactions").fetchall() == [("like", None)]
    assert _react(client, "R001", "none").status_code == 204
    assert c.execute("SELECT COUNT(*) FROM reactions").fetchone()[0] == 0
    c.close()


def test_none_only_deletes_own_device(client, dbp):
    _react(client, "R001", "like", dev="qa-dev-aaaa")
    _react(client, "R001", "like", dev="qa-dev-bbbb")
    _react(client, "R001", "none", dev="qa-dev-aaaa")
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT device_id FROM reactions").fetchall() == [("qa-dev-bbbb",)]
    c.close()


# --- 리뷰 커서 -----------------------------------------------------------
def test_cursor_all_same_timestamp_mixed_ad_every_limit(client, dbp):
    same = "2026-10-10T00:00:00+00:00"
    _insert(dbp, [(500 + i, "R005", 4.0, "협찬 받음" if i % 3 == 0 else f"맛 {i}", "[]", f"dev-{i}", same)
                  for i in range(17)])
    full = client.get("/restaurants/R005/reviews?limit=50").json()["items"]
    assert len(full) == 17
    flags = [it["ad_disclosed"] for it in full]
    assert flags == sorted(flags)  # 광고 표시 아닌 것 먼저
    for limit in (1, 2, 3, 5, 6, 16, 17):
        got, _ = _walk(client, "R005", limit)
        assert [it["id"] for it in got] == [it["id"] for it in full], limit


def test_cursor_exact_page_boundary_has_no_trailing_cursor(client, dbp):
    _insert(dbp, [(600 + i, "R006", 3.5, f"t{i}", "[]", None, f"2026-10-{i + 1:02d}T00:00:00+00:00")
                  for i in range(10)])
    r = client.get("/restaurants/R006/reviews?limit=10").json()
    assert len(r["items"]) == 10 and r["next_cursor"] is None
    r = client.get("/restaurants/R006/reviews?limit=5").json()
    r2 = client.get("/restaurants/R006/reviews", params={"limit": 5, "cursor": r["next_cursor"]}).json()
    assert len(r2["items"]) == 5 and r2["next_cursor"] is None


def test_newer_ad_review_sorted_after_older_normal(client, dbp):
    _insert(dbp, [
        (700, "R007", 5.0, "체험단 리뷰입니다", "[]", None, "2026-10-20T00:00:00+00:00"),
        (701, "R007", 2.0, "오래된 일반 리뷰", "[]", None, "2020-01-01T00:00:00+00:00"),
        (702, "R007", 3.0, "광고 아닙니다 내돈내산", "[]", None, "2026-10-19T00:00:00+00:00"),
    ])
    items = client.get("/restaurants/R007/reviews?limit=1").json()
    got, _ = _walk(client, "R007", 1)
    assert [(it["id"], it["ad_disclosed"]) for it in got] == [(702, False), (701, False), (700, True)]
    assert items["items"][0]["id"] == 702


def test_cursor_deleted_anchor_no_dup_no_skip(client, dbp):
    _insert(dbp, [(800 + i, "R008", 4.0, f"t{i}", "[]", None, f"2026-09-{i + 1:02d}T00:00:00+00:00")
                  for i in range(6)])
    p1 = client.get("/restaurants/R008/reviews?limit=3").json()
    anchor = p1["items"][-1]["id"]
    c = sqlite3.connect(dbp)
    c.execute("DELETE FROM user_reviews WHERE id=?", (anchor,))
    c.commit(); c.close()
    p2 = client.get("/restaurants/R008/reviews", params={"limit": 3, "cursor": p1["next_cursor"]}).json()
    assert [it["id"] for it in p2["items"]] == [802, 801, 800]


@pytest.mark.parametrize("payload", [
    [0, "x"], [0, "x", 1, 2], {"a": 1}, ["0", "x", 1], [0, 1, 1], [0, "x", "1"], None, "str",
])
def test_cursor_tampered_is_400(client, payload):
    cur = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert client.get("/restaurants/R001/reviews", params={"cursor": cur}).status_code == 400


def test_cursor_non_ascii_garbage_is_400(client):
    for cur in ("____", "😀", "AAAA" * 3, "%ZZ"):
        assert client.get("/restaurants/R001/reviews", params={"cursor": cur}).status_code in (400,)


def test_reviews_exclude_unrated(client, dbp):
    _insert(dbp, [(900, "R009", 0.0, "별점없음", "[]", None, "2026-10-01T00:00:00+00:00"),
                  (901, "R009", 4.0, "별점있음", "[]", None, "2026-10-01T00:00:00+00:00")])
    assert [it["id"] for it in client.get("/restaurants/R009/reviews").json()["items"]] == [901]


# --- PII ----------------------------------------------------------------
def test_no_device_id_or_user_id_anywhere(client, dbp):
    secret = "qa-secret-device-xyz"
    _react(client, "R002", "like", dev=secret)
    _insert(dbp, [(950, "R002", 4.0, "굿", "[]", secret, "2026-10-01T00:00:00+00:00")])
    responses = [
        client.get("/restaurants/R002/reviews"),
        client.get("/restaurants/R002"),
        client.post("/recommend", json={**CH, "limit": 5, "radius_m": 20000}),
    ]
    for r in responses:
        assert r.status_code == 200
        assert secret not in r.text and "user_id" not in r.text and "device_id" not in r.text
        assert "like_count" not in r.text and "reaction" not in r.text


def test_reaction_response_is_empty(client):
    r = _react(client, "R001", "like")
    assert r.status_code == 204 and r.content == b""


# --- 레이트리밋 ------------------------------------------------------------
def test_xff_spoof_does_not_bypass_ip_limit(client):
    """정책: IP 버킷 분당 IP_LIMIT_PER_MIN. 신뢰 프록시 미설정 시 XFF/X-Real-IP 위조로 IP 버킷 회피 불가."""
    codes = [client.post("/reactions", headers={"X-Forwarded-For": f"10.0.{i % 250}.{i // 250}",
                                                "X-Real-IP": f"10.1.{i % 250}.{i // 250}"},
                         json={"device_id": f"qa-rot-{i:06d}", "restaurant_id": "R001", "value": "like"}).status_code
             for i in range(IP_LIMIT_PER_MIN + 1)]
    assert codes[-1] == 429 and codes[:-1] == [204] * IP_LIMIT_PER_MIN


def test_device_rotation_does_not_bypass(client):
    """기기 ID 를 매번 바꿔도 같은 IP 는 분당 IP_LIMIT_PER_MIN 에서 막힘."""
    codes = [_react(client, "R001", "like", dev=f"qa-rot-{i:06d}").status_code for i in range(IP_LIMIT_PER_MIN + 5)]
    assert codes.count(429) == 5


def test_rejected_request_not_counted():
    rl = RateLimiter(limit=2, window_s=60)
    assert rl.allow(["d", "ip"], now=0) and rl.allow(["d2", "ip"], now=0)
    assert not rl.allow(["d", "ip"], now=1)
    assert rl.allow(["d", "ip2"], now=1)  # d 는 1회만 기록됐어야 함


def test_reaction_and_review_buckets_independent(client):
    for _ in range(WRITE_LIMIT_PER_MIN):
        assert _react(client, "R001", "like").status_code == 204
    assert _react(client, "R001", "like").status_code == 429
    assert client.post("/restaurants/R003/reviews", json={"stars": 4}).status_code == 201
    assert client.get("/restaurants/R001/reviews").status_code == 200
    assert client.post("/recommend", json=CH).status_code == 200  # 읽기/추천은 제한 없음


def test_normal_toggling_user_not_blocked(client):
    """정상 사용: 1분에 덱 5장 좋아요/취소 + 싫어요/되돌리기 (≈ 20회) 는 차단 안 됨."""
    ids = _ids(client.post("/recommend", json={**CH, "limit": 5}))
    codes = []
    for i in ids:
        codes += [_react(client, i, "like").status_code, _react(client, i, "none").status_code,
                  _react(client, i, "dislike", reason="far").status_code, _react(client, i, "none").status_code]
    assert set(codes) == {204}


def test_users_sharing_ip_not_blocked_by_each_other(client):
    for k in range(WRITE_LIMIT_PER_MIN):
        assert _react(client, "R001", "like", dev=f"qa-user-{k:05d}").status_code == 204
    assert _react(client, "R001", "like", dev="qa-user-fresh").status_code == 204


def test_rate_limiter_memory_bounded_under_device_flood():
    rl = RateLimiter(limit=1, window_s=60)
    rl.allow(["ip"], now=0)
    for i in range(1000):
        rl.allow([f"dev:{i}", "ip"], now=1)
    for i in range(1000):  # 창이 지나도 정리되지 않음
        rl.allow([f"ip-{i}"], now=1000 + i)
    assert len(rl._hits) < 100


# --- 대량 리뷰 ------------------------------------------------------------
def test_large_review_sheet_complete_and_fast(client, dbp):
    n = 3000
    _insert(dbp, [(10_000 + i, "R010", 4.0, "협찬" if i % 10 == 0 else f"리뷰 본문 {i} " * 5, '["맛"]', None,
                   f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}T00:00:00+00:00") for i in range(n)])
    t0 = time.perf_counter()
    first = client.get("/restaurants/R010/reviews?limit=20")
    one_page = time.perf_counter() - t0
    assert first.status_code == 200
    t0 = time.perf_counter()
    got, pages = _walk(client, "R010", 50)
    total = time.perf_counter() - t0
    assert len(got) == n and len({it["id"] for it in got}) == n
    assert pages == n // 50
    flags = [it["ad_disclosed"] for it in got]
    assert flags == sorted(flags)
    # 페이지당 전체 행 로드·정규식 → O(n) per page. 3000건 기준 상한만 확인(회귀 감시용)
    assert one_page < 2.0 and total < 30.0, (one_page, total)
