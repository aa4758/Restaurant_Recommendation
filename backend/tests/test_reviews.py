"""리뷰 개편(docs/01 R-0~R-7): 덮어쓰기·삭제 제한·현장 작성·새 계정 제한·메뉴 확정·가격대·분위기·내 리뷰."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import _sha256
from app.ingest.load_seed import load


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


def _loc(dbp, rid):
    return sqlite3.connect(dbp).execute("SELECT lat, lng FROM restaurants WHERE id=?", (rid,)).fetchone()


def _age(dbp, headers, days):
    """계정 가입일을 days 일 전으로."""
    c = sqlite3.connect(dbp)
    uid = c.execute("SELECT user_id FROM sessions WHERE token_hash=?", (_sha256(headers["Authorization"][7:]),)).fetchone()[0]
    c.execute("UPDATE users SET created_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), uid))
    c.commit()


def test_read_open_write_needs_login(client):
    assert client.get("/restaurants/R001/reviews").status_code == 200  # R-0
    assert client.get("/restaurants/R001/menus").status_code == 200
    assert client.post("/restaurants/R001/reviews", json={"stars": 3}).status_code == 401
    assert client.delete("/restaurants/R001/reviews/me").status_code == 401
    assert client.get("/me/reviews").status_code == 401


def test_rewrite_overwrites_and_marks_edited(client, dbp, login):
    h = login()
    a = client.post("/restaurants/R001/reviews", json={"stars": 2, "text": "별로"}, headers=h).json()
    b = client.post("/restaurants/R001/reviews", json={"stars": 4, "text": "다시 가니 좋음"}, headers=h).json()
    assert a["id"] == b["id"] and (a["updated"], b["updated"]) == (False, True)
    items = client.get("/restaurants/R001/reviews").json()["items"]
    mine = [i for i in items if i["id"] == a["id"]]
    assert len(mine) == 1 and mine[0]["stars"] == 4 and mine[0]["edited"] is True


def test_delete_once_per_day(client, login):
    h = login()
    client.post("/restaurants/R001/reviews", json={"stars": 3}, headers=h)
    assert client.delete("/restaurants/R001/reviews/me", headers=h).status_code == 204
    assert client.get("/me/reviews", headers=h).json()["items"] == []
    client.post("/restaurants/R001/reviews", json={"stars": 3}, headers=h)  # 다시 쓰기는 가능
    r = client.delete("/restaurants/R001/reviews/me", headers=h)
    assert r.status_code == 429 and "하루에 한 번" in r.json()["detail"]
    assert client.delete("/restaurants/R002/reviews/me", headers=h).status_code == 404


def test_onsite_within_200m_sticky_and_location_not_stored(client, dbp, login):
    lat, lng = _loc(dbp, "R001")
    h = login()
    far = {"lat": lat + 0.01, "lng": lng}  # 약 1.1km
    near = {"lat": lat + 0.0015, "lng": lng}  # 약 170m
    assert client.post("/restaurants/R001/reviews", json={"stars": 3, "positions": [far]}, headers=h).json()["onsite"] is False
    # 250m + 오차 60m → 허용
    assert client.post("/restaurants/R001/reviews", json={"stars": 3, "positions": [{"lat": lat + 0.00225, "lng": lng,
                       "accuracy": 60}]}, headers=h).json()["onsite"] is True
    assert client.post("/restaurants/R001/reviews", json={"stars": 3, "positions": [far]}, headers=h).json()["onsite"] is True  # R-2a
    h2 = login()
    assert client.post("/restaurants/R001/reviews", json={"stars": 3, "positions": [far, near]}, headers=h2).json()["onsite"]
    dump = "\n".join(sqlite3.connect(dbp).iterdump())
    assert repr(lat + 0.0015) not in dump and repr(lat + 0.01) not in dump  # 위치는 판정에만


def test_new_account_limits(client, dbp, login):
    h = login()
    ids = [f"R{i:03d}" for i in range(1, 13)]
    codes = [client.post(f"/restaurants/{rid}/reviews", json={"stars": 3}, headers=h).status_code for rid in ids[:4]]
    assert codes == [201, 201, 201, 429]
    # 수정은 한도에 안 셈
    assert client.post("/restaurants/R001/reviews", json={"stars": 4}, headers=h).status_code == 201
    _age(dbp, h, 8)  # 7일 지나면 24시간 20개
    assert client.post("/restaurants/R004/reviews", json={"stars": 3}, headers=h).status_code == 201


def test_menu_confirmed_by_two_accounts(client, dbp, login):
    def menus():
        return {m["name"]: m["price"] for m in client.get("/restaurants/R001/menus").json()["items"]}

    client.post("/restaurants/R001/reviews", json={"stars": 3, "menus": [{"name": "김치 찌개", "price": 9000}]}, headers=login())
    assert "김치 찌개" not in menus() and "김치찌개" not in menus()
    client.post("/restaurants/R001/reviews", json={"stars": 3, "menus": [{"name": "김치찌개", "price": 10000}]}, headers=login())
    client.post("/restaurants/R001/reviews", json={"stars": 3, "menus": [{"name": "김치찌개", "price": 90000}]}, headers=login())
    m = menus()
    assert m.get("김치찌개") == 9500  # 중앙값 10000 의 2배 초과(90000) 제외 → 9000·10000 중앙값


def test_spend_and_moods_aggregate_from_three(client, dbp, login):
    c = sqlite3.connect(dbp)
    c.execute("UPDATE restaurants SET price_band=NULL, price_src=NULL, moods='', moods_src=NULL WHERE id='R001'")
    c.commit()
    heads = [login() for _ in range(3)]
    body = [{"spend": "1~2만", "moods": ["혼밥", "조용한"]}, {"spend": "1~2만", "moods": ["혼밥"]}, {"spend": "2~4만", "moods": ["회식"]}]
    for h, b in zip(heads[:2], body[:2]):
        client.post("/restaurants/R001/reviews", json={"stars": 3, **b}, headers=h)
    d = client.get("/restaurants/R001").json()
    assert d["price_band"] == "가격 미확인" and "혼밥" not in d["moods"]  # 2개는 미달
    client.post("/restaurants/R001/reviews", json={"stars": 3, **body[2]}, headers=heads[2])
    d = client.get("/restaurants/R001").json()
    assert d["price_band"] == "1~2만" and "혼밥" in d["moods"] and "회식" not in d["moods"]
    # 삭제로 3개 미만이 되면 리뷰 집계값을 비움
    client.delete("/restaurants/R001/reviews/me", headers=heads[2])
    assert client.get("/restaurants/R001").json()["price_band"] == "가격 미확인"


def test_my_reviews_list_and_validation(client, login):
    h = login()
    client.post("/restaurants/R002/reviews", json={"stars": 4, "spend": "~1만", "moods": ["노포"],
                                                   "menus": [{"name": "국밥", "price": 8000}]}, headers=h)
    items = client.get("/me/reviews", headers=h).json()["items"]
    assert len(items) == 1 and items[0]["restaurant_id"] == "R002" and items[0]["name"]
    assert "sido" in items[0] and "sigungu" in items[0]  # I-3 지도
    assert items[0]["menus"] == [{"name": "국밥", "price": 8000}] and items[0]["moods"] == ["노포"]
    bad = [{"spend": "5만"}, {"moods": ["시끄러운"]}, {"menus": [{"name": "a"}] * 4}, {"menus": [{"name": " "}]},
           {"menus": [{"name": "x", "price": 500}]}, {"positions": [{"lat": 1, "lng": 1}] * 3}]
    for b in bad:
        assert client.post("/restaurants/R002/reviews", json={"stars": 3, **b}, headers=h).status_code == 422, b


def test_delete_account_clears_aggregates(client, dbp, login):
    heads = [login() for _ in range(3)]
    for h in heads:
        client.post("/restaurants/R001/reviews", json={"stars": 3, "spend": "4만+", "menus": [{"name": "코스"}]}, headers=h)
    assert client.get("/restaurants/R001").json()["price_band"] == "4만+"
    client.delete("/auth/me", headers=heads[0])
    c = sqlite3.connect(dbp)
    assert c.execute("SELECT COUNT(*) FROM review_menus").fetchone()[0] == 2
    assert client.get("/restaurants/R001").json()["price_band"] == "가격 미확인"
    assert "코스" in [m["name"] for m in client.get("/restaurants/R001/menus").json()["items"]]  # 남은 2계정
