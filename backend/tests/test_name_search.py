"""가게 이름 검색(docs/01 '가게 이름 검색', 2026-11-15): 해석(name·name_only)·추천 맨 앞 표시·이어 받기."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.ingest.load_seed import load

CITY_HALL = {"lat": 37.5663, "lng": 126.9779}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(p))
    load(p)
    c = sqlite3.connect(p)  # 테스트용 이름(카카오 시드는 키 없이 안 들어옴)
    for rid, name in (("R001", "부민옥"), ("R002", "광화문국밥 본점"), ("R003", "광화문미진 본점")):
        c.execute("UPDATE restaurants SET name=? WHERE id=?", (name, rid))
    c.commit()
    from app.main import app
    return TestClient(app)


def _f(client, text):
    return client.post("/filters/parse", json={"text": text}).json()["filters"]


def test_parse_name(client):
    f = _f(client, "부민옥")  # 이름으로만 읽힘
    assert f["name"] == "부민옥" and f["name_only"] is True
    f = _f(client, "광화문국밥")  # 이름 + 음식(국밥) → 둘 다
    assert f["name"] == "광화문국밥" and f["name_only"] is False and f["subtype"] == ["국밥"]
    f = _f(client, "국밥")  # 음식 낱말 그 자체는 이름 전체 일치만 → 이름이 '국밥' 인 가게 없음
    assert f["name"] is None and f["subtype"] == ["국밥"]
    assert _f(client, "없는가게이름")["name"] is None


def test_recommend_name_first_and_marked(client):
    only = client.post("/recommend", json={**CITY_HALL, "name": "부민옥", "name_only": True, "limit": 5}).json()
    assert [i["name"] for i in only["items"]] == ["부민옥"] and only["items"][0]["name_match"] and only["total"] == 1

    both = client.post("/recommend", json={**CITY_HALL, "name": "광화문", "limit": 3, "radius_m": 3000}).json()
    names = [i for i in both["items"] if i["name_match"]]
    assert len(names) == 2 and both["items"][:2] == names  # 광화문국밥 본점·광화문미진 본점이 맨 앞(가까운 순)
    assert all(not i["name_match"] for i in both["items"][2:]) and both["total"] > 3

    # 이어 받기: 겹침·빠짐 없이 이어짐
    page2 = client.post("/recommend", json={**CITY_HALL, "name": "광화문", "limit": 3, "offset": 3, "radius_m": 3000}).json()
    whole = client.post("/recommend", json={**CITY_HALL, "name": "광화문", "limit": 6, "radius_m": 3000}).json()
    assert [i["id"] for i in both["items"] + page2["items"]] == [i["id"] for i in whole["items"]]

    # 싫어요 숨김은 이름 결과에도 적용, 이름만인데 맞는 가게가 없으면 평소 추천
    hid = client.post("/recommend", json={**CITY_HALL, "name": "부민옥", "name_only": True, "exclude_ids": [only["items"][0]["id"]]}).json()
    assert hid["items"] and not any(i["name_match"] for i in hid["items"])


def test_name_not_sent_to_kakao_place(client, monkeypatch):
    """가게 이름으로 읽힌 낱말은 카카오 지명으로 찾지 않음(2026-11-15: '희옥' → 진도 '희옥들' 로 이동하던 결함)."""
    from app import nlparse
    far = {"name": "희옥들", "kind": "landmark", "label": "희옥들 (전남 진도군)", "lat": 34.44, "lng": 126.29}
    monkeypatch.setattr(nlparse, "_kakao_places", lambda tok: (far,) if tok == "부민옥" else ())
    f = _f(client, "부민옥")
    assert f["name"] == "부민옥" and f["name_only"] is True and f["place"] is None
