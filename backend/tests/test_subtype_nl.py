"""세부 분류·2단계 음식 필터·자연어 조건 해석·주간 사전 보강 (docs/01 2026-10-29)."""
import json
from datetime import date
from types import SimpleNamespace

from app import db as appdb
from app import nlp_enrich
from app.nlparse import parse
from app.scoring.recommend import Candidate, Query, recommend
from app.subtype import classify, decide


def test_classify_and_decide_order():
    assert classify("문성돼지국밥") == "돼지국밥" and classify("모두의죽 주안점") == "죽"
    assert classify("멕시카나미룡점") == "치킨" and classify("진주회관") is None
    assert decide("운정", "냉면/밀면", [], None) == ("냉면", "sbiz")
    assert decide("운정", None, ["김치찌개", "김치찌개백반", "된장찌개"], None) == ("김치찌개", "menu")
    # 넓은 상가 소분류(백반/한정식)는 기존 장르가 한식·기타일 때만
    assert decide("태성골뱅이", "백반/한정식", [], None, "주점") == (None, None)
    assert decide("왕코", "백반/한정식", [], None, "기타") == ("백반/가정식", "sbiz")


def _c(i, genre, subtype=None, star=3.0, d=0.001):
    return Candidate(id=i, name=i, genre=genre, subtype=subtype, price_band="~1만", moods=[], alcohol=False,
                     lat=37.5 + d, lng=127.0, star=star, percentile=50)


def test_two_level_food_filter_and_relax():
    g = "국밥/탕/찌개"
    cs = [_c("국밥A", g, "국밥", 4.0), _c("곰탕B", g, "곰탕/설렁탕", 4.5),
          _c("미분류C", g, None, 4.8), _c("짬뽕D", "중식", "짜장/짬뽕", 3.5), _c("피자E", "패스트푸드", "피자", 3.0)]
    q = Query(lat=37.5, lng=127.0, subtype=["국밥"], genre=["중식"], limit=2)
    items, relaxed = recommend(cs, q)
    assert {s.cand.id for s in items} == {"국밥A", "짬뽕D"} and relaxed == []  # 국밥/탕/찌개는 국밥만, 중식은 전체
    q = Query(lat=37.5, lng=127.0, subtype=["국밥"], limit=3)
    items, relaxed = recommend(cs, q)
    assert relaxed == ["subtype"] and {s.cand.id for s in items} == {"국밥A", "곰탕B", "미분류C"}  # 상위 장르로
    assert next(s for s in items if s.cand.id == "곰탕B").relaxed == ["subtype"]
    assert "국밥" in next(s for s in items if s.cand.id == "국밥A").reasons[1]


def test_parse_rules():
    r = parse("회사 근처 만원 이하 국밥집, 혼밥하기 좋고 술은 안 마셔", use_model=False)["filters"]
    assert r == {"price": ["~1만"], "subtype": ["국밥"], "mood": ["혼밥"], "alcohol": "any", "radius_m": 500}  # "no" 숨김(2026-11-12)
    r = parse("도보 10분 2만원대 고기집 회식", use_model=False)["filters"]
    assert r["radius_m"] == 800 and r["price"] == ["2~4만"] and r["genre"] == ["고기/구이"] and r["mood"] == ["회식"]
    assert parse("꾹밥 먹고 싶어", use_model=False)["filters"]["subtype"] == ["국밥"]  # 자모 오타 1
    assert parse("소주 한잔 곱창", use_model=False)["filters"] == {"subtype": ["곱창/막창"], "alcohol": "yes"}


def test_unknown_recorded_and_approved_synonym(tmp_path):
    conn = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(conn)
    for _ in range(3):
        out = parse("얼큰한 거 먹고 싶어", conn, use_model=False)
    assert out["unknown"] == ["얼큰한"] and out["filters"] == {"alcohol": "any"}
    assert tuple(conn.execute("SELECT term, count FROM unknown_terms").fetchone()) == ("얼큰한", 3)
    conn.execute("INSERT INTO synonyms VALUES('얼큰한','subtype','찌개/탕','approved',NULL,'2026-10-29')")
    assert parse("얼큰한 거", conn, use_model=False)["filters"]["subtype"] == ["찌개/탕"]


class FakeBatches:
    def __init__(self, reply):
        self.reply, self.created = reply, []

    def retrieve(self, bid):
        return SimpleNamespace(processing_status="ended")

    def results(self, bid):
        msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"items": self.reply}))])
        return [SimpleNamespace(result=SimpleNamespace(type="succeeded", message=msg))]

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=f"b{len(self.created)}")


def test_weekly_enrich_cycle(tmp_path):
    conn = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(conn)
    conn.executemany("INSERT INTO unknown_terms VALUES(?,?,?,?)", [
        ("얼큰한", 5, "2026-10-01", "2026-10-28"), ("땡초", 2, "2026-10-27", "2026-10-28"),  # 3회 미만 → 안 보냄
        ("옛말", 9, "2026-01-01", "2026-07-01")])  # 90일 지남 → 삭제
    fb = FakeBatches([{"term": "얼큰한", "field": "subtype", "value": "찌개/탕"},
                      {"term": "얼큰한", "field": "mood", "value": "찌개/탕"},  # field·value 불일치 → 버림
                      {"term": "남의말", "field": "genre", "value": "한식"}])  # 보내지 않은 낱말 → 버림
    client = SimpleNamespace(messages=SimpleNamespace(batches=fb))
    r1 = nlp_enrich.run(conn, date(2026, 10, 29), client)
    assert r1["submitted_terms"] == 1 and r1["pruned"] == 1 and r1["proposed"] == 0
    req = fb.created[0][0]["params"]
    assert req["model"] == "claude-haiku-5-5" and req["messages"][0]["content"] == "얼큰한"  # 낱말만 전송
    r2 = nlp_enrich.run(conn, date(2026, 11, 5), client)  # 다음 주: 지난 배치 수거
    assert r2["collected"] == 1 and r2["proposed"] == 1 and r2["submitted_terms"] == 0  # 제안 대기 낱말은 재전송 안 함
    assert parse("얼큰한", conn, use_model=False)["filters"] == {"alcohol": "any"}  # 승인 전엔 미사용
    assert nlp_enrich.set_status(conn, None, "approved") == 1
    assert parse("얼큰한", conn, use_model=False)["filters"]["subtype"] == ["찌개/탕"]


def test_enrich_without_client_only_prunes(tmp_path, monkeypatch):
    conn = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(conn)
    monkeypatch.setattr(nlp_enrich, "_client", lambda: None)
    assert nlp_enrich.run(conn, date(2026, 10, 29))["batch_id"] is None


def test_relax_keeps_subtype_before_missing_price_mood():
    """가격대·분위기 데이터가 없어도 고른 세부 메뉴는 지킴(분위기→가격 먼저 완화)."""
    cs = [_c(f"국밥{i}", "국밥/탕/찌개", "국밥", 4.0) for i in range(3)] + [_c("곰탕", "국밥/탕/찌개", "곰탕/설렁탕", 5.0)]
    for c in cs:
        c.price_band = "가격 미확인"
    q = Query(lat=37.5, lng=127.0, subtype=["국밥"], price=["~1만"], mood=["혼밥"], limit=3)
    items, relaxed = recommend(cs, q)
    assert relaxed == ["mood", "price"] and all(s.cand.subtype == "국밥" for s in items)


def test_genres_2026_11_and_buffet():
    """2026-11-02 세분화: 장르 17개, 뷔페도 세부 분류, 기타는 세부 분류 없음."""
    from app.constants import GENRES
    from app.subtype import PARENT, SUBTYPES
    assert len(GENRES) == 17 and GENRES[-3:] == ["카페/디저트", "뷔페", "기타"] and "기타" not in SUBTYPES
    assert set(PARENT.values()) == set(GENRES) - {"기타"} and len(PARENT) >= 100
    assert decide("애슐리 퀸즈", None, [], None) == ("뷔페", "name")
    assert decide("쿠우쿠우 강남점", None, [], None) == ("해산물/초밥 뷔페", "name")
    assert decide("한식당", None, [], None, "기타", "뷔페식") == ("뷔페", "license")
    # 오탐 방지: 베이커리의 '커리', 지명 '사천', 공항 라운지, '태평양'
    assert classify("원 고양 베이커리") == "베이커리" and classify("골프존카운티사천그늘집2") is None
    assert classify("태평양") is None and classify("봄베이인도요리전문점") == "인도/네팔"
    assert parse("부페 가고 싶어", use_model=False)["filters"] == {"genre": ["뷔페"], "alcohol": "any"}


def test_bunsik_merged():
    """2026-11-12: '분식 일반'·'순대/튀김/어묵' → '분식'. 규칙·모델 출력·기존 DB 모두."""
    import sqlite3
    from app import db as appdb
    from app.subtype import RENAMED, SUBTYPES, classify
    assert "분식" in SUBTYPES["분식"] and not {"분식 일반", "순대/튀김/어묵"} & set(SUBTYPES["분식"])
    assert classify("영희네 순대") == "분식" and classify("행복분식") == "분식"
    assert RENAMED["분식 일반"] == "분식"
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    appdb.init_schema(c)
    c.execute("INSERT INTO restaurants(id,name,genre,subtype,lat,lng) VALUES('a','x','분식','분식 일반',37,127)")
    c.execute("PRAGMA user_version = 1")
    appdb.init_schema(c)
    assert c.execute("SELECT subtype FROM restaurants").fetchone()[0] == "분식"


def test_no_etc_words_in_subtypes():
    """2026-11-12: 세부 분류 이름에 '기타'·'일반' 금지."""
    from app.subtype import RULES
    assert not [t for t, _, _ in RULES if "기타" in t or "일반" in t]


def test_place_in_query(tmp_path):
    """2026-11-12: 문장 속 지명(동·N가·시군구) → place 좌표 + 기본 반경. 가게 수 적은 동·일반 낱말은 지명 아님."""
    import sqlite3
    from app import db as appdb
    f = tmp_path / "p.db"
    c = sqlite3.connect(f)
    c.row_factory = sqlite3.Row
    appdb.init_schema(c)
    rows = [(f"a{i}", "x", "서울특별시", "마포구", f"서울특별시 마포구 연남동 {i}", 37.56 + i * 1e-5, 126.92) for i in range(25)]
    rows += [(f"b{i}", "x", "서울특별시", "성동구", f"서울특별시 성동구 성수동{1 + i % 2}가 {i}", 37.54, 127.05) for i in range(25)]
    rows += [(f"c{i}", "x", "경기도", "수원시 팔달구", f"경기도 수원시 팔달구 인계동 {i}", 37.26, 127.03) for i in range(5)]
    c.executemany("INSERT INTO restaurants(id,name,genre,status,sido,sigungu,address_jibun,lat,lng) VALUES(?,?,'양식','open',?,?,?,?,?)", rows)
    c.commit()
    r = parse("연남동 데이트 스테이크", c, use_model=False)["filters"]
    assert r["place"]["name"] == "연남동" and r["place"]["kind"] == "dong" and r["radius_m"] == 1000
    assert abs(r["place"]["lat"] - 37.56012) < 1e-4 and r["subtype"] == ["스테이크"] and r["mood"] == ["데이트"]
    assert parse("성수동에서 브런치", c, use_model=False)["filters"]["place"]["name"] == "성수동"
    assert parse("마포구 회식", c, use_model=False)["filters"]["radius_m"] == 3000
    assert parse("연남동 도보 5분 초밥", c, use_model=False)["filters"]["radius_m"] == 400  # 사용자 반경 우선
    assert "place" not in parse("인계동 냉면", c, use_model=False)["filters"]  # 가게 20곳 미만
    assert "place" not in parse("혼자 이동하면서 먹을 김밥", c, use_model=False)["filters"]


def test_place_options_and_kakao(tmp_path, monkeypatch):
    """같은 이름 지역 → place_options(시도 이름 있으면 좁힘). 주소에 없는 역·랜드마크 → 카카오 후보(2026-11-12)."""
    import sqlite3
    from app import db as appdb, nlparse
    f = tmp_path / "o.db"
    c = sqlite3.connect(f)
    c.row_factory = sqlite3.Row
    appdb.init_schema(c)
    rows = [(f"s{i}", "서울특별시", "중구", f"서울특별시 중구 신당동 {i}", 37.56, 127.01) for i in range(30)]
    rows += [(f"p{i}", "부산광역시", "중구", f"부산광역시 중구 남포동{1 + i % 2}가 {i}", 35.10, 129.03) for i in range(25)]
    c.executemany("INSERT INTO restaurants(id,name,genre,status,sido,sigungu,address_jibun,lat,lng) VALUES(?,'x','한식','open',?,?,?,?,?)", rows)
    c.commit()
    r = parse("중구 노포", c, use_model=False)
    assert "place" not in r["filters"] and r["filters"]["radius_m"] == 3000
    assert [o["label"] for o in r["place_options"]] == ["서울특별시 중구", "부산광역시 중구"]  # 가게 많은 순
    r = parse("부산 중구 노포", c, use_model=False)
    assert r["filters"]["place"]["label"] == "부산광역시 중구" and "place_options" not in r

    fake = {"강남역": ({"name": "강남역 2호선", "kind": "landmark", "label": "강남역 2호선 (서울 강남구)", "lat": 37.4979, "lng": 127.0276},),
            "시청역": ({"name": "시청역 1호선", "kind": "landmark", "label": "시청역 1호선 (서울 중구)", "lat": 37.56, "lng": 126.97},
                     {"name": "시청역 1호선", "kind": "landmark", "label": "시청역 1호선 (부산 연제구)", "lat": 35.18, "lng": 129.07})}
    monkeypatch.setattr(nlparse, "_kakao_places", lambda tok: fake.get(tok, ()))
    r = parse("강남역 초밥", c, use_model=False)
    assert r["filters"]["place"]["name"] == "강남역 2호선" and r["filters"]["radius_m"] == 1000 and "강남역" not in r["unknown"]
    assert len(parse("시청역 국밥", c, use_model=False)["place_options"]) == 2  # 역 이름('시청')으로 좁히지 않음
    assert parse("부산 시청역 국밥", c, use_model=False)["filters"]["place"]["label"] == "시청역 1호선 (부산 연제구)"
    assert "place" not in parse("국밥", c, use_model=False)["filters"]


def test_sido_word_and_single_hoe():
    """'부산'을 음식 오타(수산 → 회)로 보지 않음, 한 글자 '회'는 회/횟집(2026-11-12)."""
    assert parse("부산 국밥", use_model=False)["filters"]["subtype"] == ["국밥"]
    assert parse("해운대 회", use_model=False)["filters"]["subtype"] == ["회/횟집"]
    assert parse("회식 삼겹살", use_model=False)["filters"]["mood"] == ["회식"]
