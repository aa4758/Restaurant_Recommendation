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
    for rid, name in (("R001", "부민옥"), ("R002", "광화문국밥 본점"), ("R003", "광화문미진 본점"),
                      ("R004", "멘야준"), ("R005", "돈카츠 희옥"), ("R006", "오젠(OZEN)"), ("R007", "호식이두마리치킨 시청점")):
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


def test_name_variants(client):
    """1·2단계(2026-11-15): 여러 낱말·이름 속 낱말·기호·띄어쓰기 차이."""
    assert _f(client, "소바하우스 멘야준")["name"] == "멘야준"  # 여러 낱말 중 이름 낱말(음식 해석보다 먼저)
    assert _f(client, "희옥")["name"] == "희옥"  # 이름 속 낱말(돈카츠 희옥)
    assert _f(client, "오젠")["name"] == "오젠" and _f(client, "ozen")["name"] == "ozen"  # 괄호·영문
    f = _f(client, "호식이 두마리 치킨")  # 띄어쓰기 달라도 이름 앞부분, 음식(치킨)도 → 둘 다
    assert f["name"] == "호식이 두마리 치킨" and f["genre"] == ["치킨"] and f["name_only"] is False
    items = client.post("/recommend", json={**CITY_HALL, "name": "희옥", "name_only": True}).json()["items"]
    assert [i["name"] for i in items] == ["돈카츠 희옥"] and items[0]["name_match"]


def test_place_token_is_not_name(client, monkeypatch):
    """지명으로 쓰인 낱말은 이름 아님 → 나머지 낱말로(홍대 미미네 → 미미네). 카카오 1위가 음식점이면 지명 아님."""
    from app import nlparse
    place = {"name": "광화문", "kind": "landmark", "label": "광화문 (서울 종로구)", "lat": 37.5759, "lng": 126.9768}
    monkeypatch.setattr(nlparse, "_kakao_places", lambda tok: (place,) if tok == "광화문" else ())
    f = _f(client, "광화문 부민옥")
    assert f["place"]["name"] == "광화문" and f["name"] == "부민옥"
    f = _f(client, "광화문")  # 이름 앞부분(광화문국밥 본점)만 맞음 → 지명
    assert f["place"]["name"] == "광화문" and f["name"] is None


def test_kakao_store_first_is_not_place(monkeypatch):
    """카카오 검색 1위가 음식점·카페면 지명으로 안 씀(희옥 → 진도 '희옥들' X)."""
    import io
    import json
    import urllib.request

    from app import nlparse
    docs = [{"place_name": "희옥", "category_group_code": "FD6", "category_name": "음식점", "address_name": "서울 마포구 망원동", "x": "126.9", "y": "37.5"},
            {"place_name": "희옥들", "category_group_code": "AT4", "category_name": "여행 > 관광", "address_name": "전남 진도군", "x": "126.2", "y": "34.4"}]
    monkeypatch.setenv("KAKAO_REST_KEY", "test")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps({"documents": docs}).encode()))
    nlparse._kakao_places.cache_clear()
    try:
        assert nlparse._kakao_places("희옥") == ()
        docs.reverse()
        nlparse._kakao_places.cache_clear()
        assert nlparse._kakao_places("희옥")[0]["name"] == "희옥들"
    finally:
        nlparse._kakao_places.cache_clear()
