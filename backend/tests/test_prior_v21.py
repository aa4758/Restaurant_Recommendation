"""점수 모델 v2.1 (docs/01_planning_decision.md "v2.1"): 외부 평판·백년가게·착한가격·지정 목록 매칭·reasons."""
from __future__ import annotations

import csv
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db as appdb
from app.ingest.load_designations import load_designations
from app.ingest.load_seed import load
from app.ingest.matcher import addresses_match, names_match, normalize_name, normalize_road_address
from app.scoring import prior
from app.scoring.recommend import Candidate, Query, Scored, make_reasons, recommend

NOW = date(2026, 10, 26)


# --- 외부 평판 -------------------------------------------------------------------
def test_guide_score_table():
    assert prior.GUIDE_SCORES == {
        "michelin_star": 1.0, "michelin_bib": 0.85, "taste_of_seoul": 0.85,
        "michelin_selected": 0.7, "seoul_future_heritage": 0.7, "local_food": 0.7, "gyeonggi_best": 0.7,
    }
    for kind, v in prior.GUIDE_SCORES.items():
        p = prior.prior_parts(now=NOW, designations=[kind])
        assert p.components["reputation"] == pytest.approx(prior.W_REPUTATION * v)
        assert p.components["designation"] == 0  # 가이드는 지정업소 아님


def test_reputation_is_max_of_guides_and_partner():
    assert prior.reputation_score(["local_food", "taste_of_seoul"], None) == 0.85  # 여러 가이드 → 최댓값
    assert prior.reputation_score(["local_food"], 5.0) == 1.0  # 제휴가 더 높으면 제휴
    assert prior.reputation_score(["taste_of_seoul"], 3.0) == 0.85  # 가이드가 더 높으면 가이드
    assert prior.reputation_score(["model_restaurant", "good_price"], None) == prior.REPUTATION_NEUTRAL


def test_neutral_04_and_low_partner_below_neutral():
    assert prior.REPUTATION_NEUTRAL == 0.4
    neutral = prior.prior_parts(now=NOW)
    low = prior.prior_parts(now=NOW, partner_rating=1.5)
    assert neutral.components["reputation"] == pytest.approx(0.08)
    assert low.components["reputation"] < neutral.components["reputation"]
    assert low.prior_raw < neutral.prior_raw


def test_reputation_evidence_counts_guide_or_partner():
    assert prior.prior_parts(now=NOW).evidence == "low"
    assert prior.prior_parts(now=NOW, designations=["seoul_future_heritage"]).evidence == "mid"
    assert prior.prior_parts(now=NOW, partner_rating=1.0).evidence == "mid"
    # 가이드 + 제휴 = 외부 평판 신호 1개
    assert prior.prior_parts(now=NOW, designations=["local_food"], partner_rating=4.0).evidence == "mid"


def test_designation_kinds_v21():
    assert set(prior.DESIGNATION_KINDS) == {"model_restaurant", "safe_restaurant", "origin_label_excellent"}
    assert prior.designation_score(["origin_label_excellent"]) == 1.0
    assert prior.designation_score(["century_store"]) == 0.0 and prior.designation_score(["good_price"]) == 0.0


# --- 백년가게: 업력 보정 ------------------------------------------------------------
def test_century_store_tenure_floor_no_double_bonus():
    floor = prior.tenure_score(None, NOW, century_store=True)
    assert floor == 1.0  # 30년 간주 ≥ 20년 cap
    missing = prior.prior_parts(now=NOW, designations=["century_store"])
    short = prior.prior_parts(now=NOW, opened_at="2024-01-01", designations=["century_store"])
    long_ = prior.prior_parts(now=NOW, opened_at="1980-01-01")
    long_century = prior.prior_parts(now=NOW, opened_at="1980-01-01", designations=["century_store"])
    assert missing.components["tenure"] == short.components["tenure"] == pytest.approx(prior.W_TENURE)
    assert long_century.prior_raw == pytest.approx(long_.prior_raw)  # 이중 가점 없음
    assert missing.components["designation"] == 0 and missing.components["reputation"] == pytest.approx(0.08)
    assert missing.evidence == "mid"  # 업력 신호 1개로만 집계


# --- 착한가격: 점수 무관 + 가성비 태그 ------------------------------------------------------
def test_good_price_no_score_effect():
    base = prior.prior_parts(now=NOW, opened_at="2015-01-01", hygiene_grade="우수")
    gp = prior.prior_parts(now=NOW, opened_at="2015-01-01", hygiene_grade="우수", designations=["good_price"])
    assert gp.prior_raw == base.prior_raw and gp.components == base.components and gp.evidence == base.evidence


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(path))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(path)
    return path


def test_good_price_mood_synthesized_and_filtered(seeded):
    from app.main import app
    c = TestClient(app)
    conn = sqlite3.connect(seeded)
    raw = conn.execute("SELECT moods, lat, lng FROM restaurants WHERE id='R018'").fetchone()
    assert "가성비" not in raw[0].split("|")  # 원본 미수정
    d = c.get("/restaurants/R018").json()
    assert "가성비" in d["moods"] and d["moods"].count("가성비") == 1
    assert conn.execute("SELECT moods FROM restaurants WHERE id='R018'").fetchone()[0] == raw[0]
    # limit 1: 분위기가 먼저 완화되는 순서(2026-10-29)에서도 합성 '가성비'로 R018 이 매칭되면 완화 없음
    r = c.post("/recommend", json={"lat": raw[1], "lng": raw[2], "radius_m": 300, "mood": ["가성비"], "limit": 1})
    body = r.json()
    assert "mood" not in body["relaxed"] and all("가성비" in it["moods"] for it in body["items"])
    assert body["items"]


def test_seed_v21_signals_and_mean(seeded):
    from app.main import app
    c = TestClient(app)
    stars = [c.get(f"/restaurants/R{i:03d}").json()["star"] for i in range(1, 49)]
    assert abs(sum(stars) / len(stars) - 2.5) < 0.15
    b = c.get("/restaurants/R016").json()["score_breakdown"]["components"]
    assert b["reputation"] >= prior.W_REPUTATION * 0.85 - 1e-3  # 가이드 0.85 이상(제휴가 더 높으면 제휴)
    assert set(b) == set(prior.COMPONENT_KEYS) and "partner" not in b


# --- reasons ---------------------------------------------------------------------
def _cand(**kw) -> Candidate:
    base = dict(id="X", name="x", genre="한식", price_band="1~2만", moods=[], alcohol=False,
                lat=37.5663, lng=126.9779, star=3.0, percentile=30)
    base.update(kw)
    return Candidate(**base)


def test_reasons_guide_priority_and_wording():
    q = Query(lat=37.5663, lng=126.9779)
    c = _cand(guides=["서울미식 100선 선정(2025)"], gov_visits=4, gov_source="샘플", tenure_years=40,
              century_store=True)
    r = make_reasons(Scored(c, 0, 3.0), q)
    assert len(r) == 3
    assert r[2].startswith("서울미식 100선 선정(2025)") and "업무추진비 기록 4회" in r[2]
    assert "백년가게" not in r[2]  # 최대 2개 항목
    r = make_reasons(Scored(_cand(gov_visits=2, century_store=True), 0, 3.0), q)
    assert r[2].startswith("공공기관 업무추진비 기록 2회") and "백년가게 지정" in r[2]
    r = make_reasons(Scored(_cand(century_store=True, tenure_years=3), 0, 3.0), q)
    assert r[2].startswith("백년가게 지정")
    for line in r:
        assert "공직자" not in line


def test_reasons_guide_year_from_base_date(seeded):
    from app.main import app
    c = TestClient(app)
    d = c.get("/restaurants/R016").json()
    assert "서울미식 100선 선정(2025)" == d["reasons"][2].split(" · ")[0]
    assert len(d["reasons"]) == 3
    assert "백년가게 지정" in c.get("/restaurants/R027").json()["reasons"][2]


# --- 매처 ------------------------------------------------------------------------
def test_name_normalization():
    assert normalize_name("(주)샘플식당 시청점") == normalize_name("샘플 식당") == "샘플식당"
    assert normalize_name("㈜샘플식당(본점)") == "샘플식당"
    assert names_match("샘플식당시청점", "샘플식당") and names_match("샘플식당", "주식회사 샘플식당 을지로점")
    assert not names_match("샘플식당", "샘플분식") and not names_match("", "샘플식당")


def test_road_address_normalization():
    a = normalize_road_address("서울특별시 중구 샘플로1길 70, 2층 (가상동)")
    assert a == ("서울", "중구", "샘플로1길", "70") == normalize_road_address("서울 중구 샘플로 1길 70 (가상주소)")
    assert addresses_match("중구 샘플로 1길 70", "서울 중구 샘플로1길 70")  # 시도 생략 허용
    assert not addresses_match("부산광역시 중구 샘플로 1길 70", "서울 중구 샘플로 1길 70")
    assert not addresses_match("서울 중구 샘플로 1길 71", "서울 중구 샘플로 1길 70")
    assert normalize_road_address("주소 없음") is None


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "address", "lat", "lng", "kind", "base_date", "source"])
        w.writerows(rows)


def test_matcher_load_and_unmatched_output(seeded, tmp_path):
    conn = appdb.connect(seeded)
    r1 = conn.execute("SELECT name, address, lat, lng FROM restaurants WHERE id='R001'").fetchone()
    r2 = conn.execute("SELECT name, address, lat, lng FROM restaurants WHERE id='R002'").fetchone()
    r3 = conn.execute("SELECT name, address, lat, lng FROM restaurants WHERE id='R003'").fetchone()
    before = conn.execute("SELECT components FROM scores WHERE restaurant_id='R001'").fetchone()[0]
    src = tmp_path / "list.csv"
    _write(src, [
        # 주소 일치(지점명·(주)·주소 표기 차이), 좌표 없음
        [f"(주){r1['name']} 시청점", r1["address"].replace("서울", "서울특별시").replace(" (가상주소)", ""), "", "",
         "taste_of_seoul", "2025-04-01", "서울미식 100선(가상)"],
        # 주소 다르지만 30m 이내
        [r2["name"], "서울 중구 다른로 9", r2["lat"] + 0.00027, r2["lng"], "local_food", "2024-01-01", "향토음식점(가상)"],
        # 상호 일치·주소 불일치·80m → 실패
        [r3["name"], "서울 중구 다른로 9", r3["lat"] + 0.00072, r3["lng"], "local_food", "2024-01-01", "향토음식점(가상)"],
        # 상호 불일치 → 실패
        ["없는가게", r1["address"], "", "", "taste_of_seoul", "2025-04-01", "서울미식 100선(가상)"],
        # 미슐랭은 기본 보류
        [r1["name"], r1["address"], "", "", "michelin_star", "2025-04-01", "미슐랭(가상)"],
    ])
    out = tmp_path / "out"
    res = load_designations(conn, src, out)
    assert res["matched"] == 2 and res["inserted"] == 2 and res["unmatched"] == 3
    kinds = {(r[0], r[1]) for r in conn.execute(
        "SELECT restaurant_id, kind FROM restaurant_signals WHERE kind IN ('taste_of_seoul','local_food')")}
    assert ("R001", "taste_of_seoul") in kinds and ("R002", "local_food") in kinds and ("R003", "local_food") not in kinds
    # 해당 시군구 재계산 반영
    after = conn.execute("SELECT components FROM scores WHERE restaurant_id='R001'").fetchone()[0]
    assert after != before and '"reputation": 0.17' in after
    files = {p.name for p in out.iterdir()}
    assert files == {"unmatched_향토음식점_가상.csv", "unmatched_서울미식_100선_가상.csv", "unmatched_미슐랭_가상.csv"}
    with open(out / "unmatched_향토음식점_가상.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["name"] == r3["name"] and "50m" in rows[0]["reason"]
    # 재적재 멱등(신호 중복 없음)
    again = load_designations(conn, src, out)
    assert again["matched"] == 2 and again["inserted"] == 0


def test_unmatched_dir_gitignored():
    from pathlib import Path
    gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert "backend/data/out/" in gi.splitlines()


def test_detail_designations_display_only(seeded):
    """상세 응답 designations(2026-11-05): 지정업소 표시명 + 백년가게, 고정 순서. 추천 item 에는 없음."""
    from app.main import app
    c = TestClient(app)
    assert c.get("/restaurants/R023").json()["designations"] == ["모범음식점", "안심식당"]
    assert c.get("/restaurants/R007").json()["designations"] == ["백년가게"]
    d = c.get("/restaurants/R001").json()
    assert isinstance(d["designations"], list)
    r = c.post("/recommend", json={"lat": d["lat"], "lng": d["lng"], "radius_m": 300, "limit": 1}).json()
    assert all("designations" not in it for it in r["items"])
