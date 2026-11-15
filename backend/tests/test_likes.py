"""좋아요 계정 저장(docs/01 L-1): 로그인 필수·합치기(중복·없는 가게 무시)·삭제·탈퇴 삭제·점수 무관."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load


@pytest.fixture()
def dbp(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(p))
    load(p)
    return p


@pytest.fixture()
def client(dbp):
    from app.main import app
    return TestClient(app)


def test_likes_flow(client, dbp, login):
    assert client.get("/me/likes").status_code == 401
    assert client.post("/me/likes", json={"ids": ["R001"]}).status_code == 401
    star_before = sqlite3.connect(dbp).execute("SELECT star FROM scores WHERE restaurant_id='R001'").fetchone()

    h = login()
    assert client.post("/me/likes", json={"ids": ["R001", "R002", "R001", "없는가게"]}, headers=h).status_code == 204
    assert client.post("/me/likes", json={"ids": ["R002"]}, headers=h).status_code == 204  # 이미 있음 → 무시
    items = client.get("/me/likes", headers=h).json()["items"]
    assert sorted(i["restaurant_id"] for i in items) == ["R001", "R002"]
    assert {"name", "sido", "sigungu", "dong", "food", "star", "created_at"} <= items[0].keys()

    assert login() != h and client.get("/me/likes", headers=login()).json()["items"] == []  # 다른 계정과 분리
    assert client.delete("/me/likes/R001", headers=h).status_code == 204
    assert [i["restaurant_id"] for i in client.get("/me/likes", headers=h).json()["items"]] == ["R002"]
    assert client.post("/me/likes", json={"ids": []}, headers=h).status_code == 422

    # 점수 무관(개인화 전용)
    assert sqlite3.connect(dbp).execute("SELECT star FROM scores WHERE restaurant_id='R001'").fetchone() == star_before

    # 탈퇴하면 삭제
    assert client.delete("/auth/me", headers=h).status_code == 204
    assert sqlite3.connect(dbp).execute("SELECT COUNT(*) FROM user_likes").fetchone()[0] == 0


def test_jibun_dong():
    from app.nlparse import jibun_dong
    assert jibun_dong("서울특별시 마포구 서교동 1-2") == "서교동"
    assert jibun_dong("경기도 수원시 팔달구 인계동 100") == "인계동"
    assert jibun_dong("세종특별자치시 조치원읍 1") == "조치원읍"  # 세종은 시군구 없음
    assert jibun_dong("서울특별시 중구 다동 60-0") == "다동"
    assert jibun_dong(None) is None
