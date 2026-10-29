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
    assert classify("문성돼지국밥") == "국밥/곰탕/설렁탕"
    assert classify("멕시카나미룡점") == "치킨" and classify("진주회관") is None
    assert decide("운정", "냉면/밀면", [], None) == ("냉면/국수/칼국수", "sbiz")
    assert decide("운정", None, ["김치찌개", "된장찌개", "제육덮밥"], None) == ("찌개/전골", "menu")
    # 넓은 상가 소분류(백반/한정식)는 기존 장르가 한식·기타일 때만
    assert decide("태성골뱅이", "백반/한정식", [], None, "주점") == (None, None)
    assert decide("왕코", "백반/한정식", [], None, "기타") == ("백반·가정식", "sbiz")


def _c(i, genre, subtype=None, star=3.0, d=0.001):
    return Candidate(id=i, name=i, genre=genre, subtype=subtype, price_band="~1만", moods=[], alcohol=False,
                     lat=37.5 + d, lng=127.0, star=star, percentile=50)


def test_two_level_food_filter_and_relax():
    cs = [_c("국밥A", "한식", "국밥/곰탕/설렁탕", 4.0), _c("냉면B", "한식", "냉면/국수/칼국수", 4.5),
          _c("미분류C", "한식", None, 4.8), _c("짬뽕D", "중식", "짜장/짬뽕", 3.5), _c("피자E", "양식", "피자", 3.0)]
    q = Query(lat=37.5, lng=127.0, subtype=["국밥/곰탕/설렁탕"], genre=["중식"], limit=2)
    items, relaxed = recommend(cs, q)
    assert {s.cand.id for s in items} == {"국밥A", "짬뽕D"} and relaxed == []  # 한식은 국밥만, 중식은 전체
    q = Query(lat=37.5, lng=127.0, subtype=["국밥/곰탕/설렁탕"], limit=3)
    items, relaxed = recommend(cs, q)
    assert relaxed == ["subtype"] and {s.cand.id for s in items} == {"국밥A", "냉면B", "미분류C"}  # 상위 장르로
    assert next(s for s in items if s.cand.id == "냉면B").relaxed == ["subtype"]
    assert "국밥/곰탕/설렁탕" in next(s for s in items if s.cand.id == "국밥A").reasons[1]


def test_parse_rules():
    r = parse("회사 근처 만원 이하 국밥집, 혼밥하기 좋고 술은 안 마셔", use_model=False)["filters"]
    assert r == {"price": ["~1만"], "subtype": ["국밥/곰탕/설렁탕"], "mood": ["혼밥"], "alcohol": "no", "radius_m": 500}
    r = parse("도보 10분 2만원대 고기집 회식", use_model=False)["filters"]
    assert r["radius_m"] == 800 and r["price"] == ["2~4만"] and r["genre"] == ["고기/구이"] and r["mood"] == ["회식"]
    assert parse("꾹밥 먹고 싶어", use_model=False)["filters"]["subtype"] == ["국밥/곰탕/설렁탕"]  # 자모 오타 1
    assert parse("소주 한잔 곱창", use_model=False)["filters"] == {"subtype": ["곱창/막창"], "alcohol": "yes"}


def test_unknown_recorded_and_approved_synonym(tmp_path):
    conn = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(conn)
    for _ in range(3):
        out = parse("얼큰한 거 먹고 싶어", conn, use_model=False)
    assert out["unknown"] == ["얼큰한"] and out["filters"] == {"alcohol": "any"}
    assert tuple(conn.execute("SELECT term, count FROM unknown_terms").fetchone()) == ("얼큰한", 3)
    conn.execute("INSERT INTO synonyms VALUES('얼큰한','subtype','찌개/전골','approved',NULL,'2026-10-29')")
    assert parse("얼큰한 거", conn, use_model=False)["filters"]["subtype"] == ["찌개/전골"]


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
    fb = FakeBatches([{"term": "얼큰한", "field": "subtype", "value": "찌개/전골"},
                      {"term": "얼큰한", "field": "mood", "value": "찌개/전골"},  # field·value 불일치 → 버림
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
    assert parse("얼큰한", conn, use_model=False)["filters"]["subtype"] == ["찌개/전골"]


def test_enrich_without_client_only_prunes(tmp_path, monkeypatch):
    conn = appdb.connect(tmp_path / "t.db")
    appdb.init_schema(conn)
    monkeypatch.setattr(nlp_enrich, "_client", lambda: None)
    assert nlp_enrich.run(conn, date(2026, 10, 29))["batch_id"] is None
