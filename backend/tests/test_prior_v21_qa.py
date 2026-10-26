"""품질검증: 점수 모델 v2.1 (docs/01 "v2.1" + API 계약 components)."""
from __future__ import annotations

import csv
import json
import math
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db as appdb
from app.ingest.load_designations import load_designations
from app.ingest.load_seed import load
from app.ingest.matcher import MATCH_RADIUS_M, RestaurantIndex, addresses_match, names_match, normalize_road_address
from app.scoring import prior
from app.scoring.recommend import Candidate, Query, Scored, make_reasons

NOW = date(2026, 10, 1)
M_LAT = 111_195.0  # haversine(R=6371km) 기준 위도 1도 거리(m)


# --- 가이드 점수표 · 최댓값 · 중립 ---------------------------------------------------
def test_guide_table_exact_and_max_and_neutral():
    assert prior.GUIDE_SCORES == {
        "michelin_star": 1.0, "michelin_bib": 0.85, "taste_of_seoul": 0.85,
        "michelin_selected": 0.7, "seoul_future_heritage": 0.7, "local_food": 0.7, "gyeonggi_best": 0.7,
    }
    assert prior.reputation_score(["local_food", "taste_of_seoul", "michelin_star"], None) == 1.0
    assert prior.reputation_score(["local_food", "seoul_future_heritage"], None) == 0.7
    # 지정업소·백년가게·착한가격은 외부 평판 아님 → 중립
    assert prior.reputation_score(["model_restaurant", "century_store", "good_price"], None) == 0.4
    assert prior.reputation_score([], 5.0) == 1.0 and prior.reputation_score(["local_food"], 4.0) == 0.75
    p = prior.prior_parts(now=NOW)
    assert math.isclose(p.components["reputation"], 0.2 * 0.4) and p.evidence == "low"


# --- 백년가게 ----------------------------------------------------------------
@pytest.mark.parametrize("opened", [None, "2020-01-01", "1960-01-01"])
def test_century_store_no_double_bonus(opened):
    base = prior.prior_parts(now=NOW, opened_at=opened)
    cs = prior.prior_parts(now=NOW, opened_at=opened, designations=["century_store"])
    assert math.isclose(cs.components["tenure"], 0.30 * min(math.log1p(30) / math.log1p(20), 1.0))
    assert cs.components["reputation"] == base.components["reputation"]
    assert cs.components["designation"] == base.components["designation"] == 0
    assert cs.prior_raw - base.prior_raw == pytest.approx(cs.components["tenure"] - base.components["tenure"])
    # 근거 수: 업력 1개만(이중 계산 없음)
    assert cs.evidence == "mid"


# --- 착한가격 ---------------------------------------------------------------
def test_good_price_zero_effect_everywhere():
    kw = dict(now=NOW, opened_at="2010-01-01", gov_visits=3, hygiene_grade="우수", partner_rating=3.0)
    a, b = prior.prior_parts(**kw), prior.prior_parts(**kw, designations=["good_price"])
    assert a == b


# --- 지정업소 3종 ------------------------------------------------------------
@pytest.mark.parametrize("k", ["model_restaurant", "safe_restaurant", "origin_label_excellent"])
def test_designation_three_kinds(k):
    assert prior.designation_score([k]) == 1.0
    assert prior.designation_score([k, *prior.DESIGNATION_KINDS]) == 1.0  # 여러 개여도 1
    assert prior.DESIGNATION_LABELS[k]
    assert k in prior.SIGNAL_KINDS


# --- evidence --------------------------------------------------------------
def test_evidence_reputation_only_when_value_present():
    assert prior.prior_parts(now=NOW).evidence == "low"
    assert prior.prior_parts(now=NOW, partner_rating=1.0).evidence == "mid"  # 기여 0 이어도 값이 있으면
    assert prior.prior_parts(now=NOW, designations=["good_price"]).evidence == "low"
    assert prior.prior_parts(now=NOW, designations=["taste_of_seoul", "michelin_bib"]).evidence == "mid"
    assert prior.prior_parts(
        now=NOW, designations=["taste_of_seoul", "safe_restaurant"], hygiene_grade="좋음").evidence == "high"


# --- 매처 -------------------------------------------------------------------
@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(path))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(path)
    return path


def _mem(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(appdb.SCHEMA)
    for i, (name, branch, addr, lat, lng, *st) in enumerate(rows):
        conn.execute("INSERT INTO restaurants(id,name,branch,genre,lat,lng,address,status) VALUES(?,?,?,?,?,?,?,?)",
                     (f"T{i}", name, branch, "한식", lat, lng, addr, st[0] if st else "open"))
    return conn


def test_radius_boundary_and_no_coords():
    lat0, lng0 = 37.5600, 126.9800
    idx = RestaurantIndex(_mem([("경계식당", None, "서울 중구 가상로 1", lat0, lng0)]))
    inside = lat0 + (MATCH_RADIUS_M - 0.5) / M_LAT
    outside = lat0 + (MATCH_RADIUS_M + 0.5) / M_LAT
    assert idx.match("경계식당", None, inside, lng0)[0] is not None
    assert idx.match("경계식당", None, outside, lng0)[0] is None
    # 좌표 없음: 주소로만
    assert idx.match("경계식당", "서울특별시 중구 가상로 1", None, None)[0].id == "T0"
    r, why = idx.match("경계식당", "서울 중구 가상로 2", None, None)
    assert r is None and "좌표 없음" in why
    r, why = idx.match("경계식당", None, lat0, None)  # 좌표 반쪽 → 좌표 없음 취급
    assert r is None


def test_different_name_never_matches_even_same_address():
    idx = RestaurantIndex(_mem([("가상국밥", None, "서울 중구 가상로 1", 37.56, 126.98)]))
    assert idx.match("가상냉면", "서울 중구 가상로 1", 37.56, 126.98)[0] is None
    assert not names_match("가상국밥", "가상국밥집")


def test_jibun_dong_ga_not_parsed_as_road():
    assert normalize_road_address("서울 중구 을지로1가 180") is None or not addresses_match(
        "서울 중구 을지로1가 180", "서울 중구 을지로1가 10")


def test_jibun_address_does_not_match_other_building():
    idx = RestaurantIndex(_mem([("가상김밥", None, "서울 중구 을지로 1", 37.5660, 126.9780)]))
    # 목록 행: 지번 '을지로3가 무관' → 위치 1km 이상 떨어진 가게
    r, _ = idx.match("가상김밥", "서울 중구 을지로1가 50", 37.5760, 126.9900)
    assert r is None


def test_floor_without_comma():
    assert addresses_match("서울 중구 세종대로 110 1층", "서울특별시 중구 세종대로 110")


def test_explicit_different_branch_not_matched():
    lat, lng = 37.5660, 126.9780
    idx = RestaurantIndex(_mem([("가상치킨", "을지로점", "서울 중구 가상로 10", lat, lng)]))
    r, _ = idx.match("가상치킨 시청점", None, lat + 30 / M_LAT, lng)  # 30m 옆 다른 지점
    assert r is None


def test_closed_restaurant_not_preferred():
    idx = RestaurantIndex(_mem([
        ("가상분식", None, "서울 중구 가상로 5", 37.5660, 126.9780, "closed"),
        ("가상분식", None, "서울 중구 가상로 5", 37.5660, 126.9780, "open"),
    ]))
    assert idx.match("가상분식", "서울 중구 가상로 5", None, None)[0].id == "T1"


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


H = ["name", "address", "lat", "lng", "kind", "base_date", "source"]


def test_unmatched_output_has_no_extra_pii_columns(seeded, tmp_path):
    conn = appdb.connect(seeded)
    src = tmp_path / "l.csv"
    _write(src, H + ["대표자명", "전화번호"], [["없는가게", "서울 중구 없는로 1", "", "", "local_food",
                                           "2024-01-01", "향토(가상)", "홍길동", "010-0000-0000"]])
    out = tmp_path / "out"
    load_designations(conn, src, out)
    text = next(out.iterdir()).read_text(encoding="utf-8-sig")
    assert "홍길동" not in text and "010-0000-0000" not in text


def test_unmatched_basic_columns_and_michelin_default_off(seeded, tmp_path):
    conn = appdb.connect(seeded)
    r1 = conn.execute("SELECT name, address FROM restaurants WHERE id='R001'").fetchone()
    src = tmp_path / "m.csv"
    _write(src, H, [[r1["name"], r1["address"], "", "", k, "2025-01-01", "미슐랭(가상)"] for k in prior.MICHELIN_KINDS])
    res = load_designations(conn, src, tmp_path / "out")
    assert res["matched"] == 0 and res["unmatched"] == 3
    assert conn.execute("SELECT COUNT(*) FROM restaurant_signals WHERE kind LIKE 'michelin%'").fetchone()[0] == 0
    res = load_designations(conn, src, tmp_path / "out", allow_michelin=True)
    assert res["matched"] == 3


def test_michelin_gate_on_signals_csv(seeded, tmp_path):
    from app.ingest.csv_adapters import RestaurantSignalsCSVAdapter
    p = tmp_path / "sig.csv"
    _write(p, ["restaurant_id", "kind", "value", "detail", "base_date", "source"],
           [["R001", "michelin_star", "1", "", "2025-01-01", "미슐랭(가상)"]])
    load(seeded, [RestaurantSignalsCSVAdapter(p)], reset=False)
    conn = sqlite3.connect(seeded)
    assert conn.execute("SELECT COUNT(*) FROM restaurant_signals WHERE kind='michelin_star'").fetchone()[0] == 0


def test_seed_has_no_michelin():
    from app.ingest.load_seed import SEED_DIR
    assert "michelin" not in (SEED_DIR / "restaurant_signals.csv").read_text(encoding="utf-8")


# --- 구DB(partner 키) 호환 ----------------------------------------------------
def test_old_partner_key_db_rebuilt(seeded):
    conn = sqlite3.connect(seeded)
    for rid, comps in conn.execute("SELECT restaurant_id, components FROM scores").fetchall():
        d = json.loads(comps)
        d["partner"] = d.pop("reputation")
        conn.execute("UPDATE scores SET components=? WHERE restaurant_id=?", (json.dumps(d), rid))
    conn.execute("PRAGMA user_version = 0")  # v2.1 이전 DB(마이그레이션 기록 없음) 재현
    conn.commit()
    conn.close()
    from app.main import app
    b = TestClient(app).get("/restaurants/R016").json()["score_breakdown"]["components"]
    assert set(b) == set(prior.COMPONENT_KEYS) and b["reputation"] > 0
    conn = sqlite3.connect(seeded)
    assert conn.execute("SELECT COUNT(*) FROM scores WHERE components LIKE '%\"partner\"%'").fetchone()[0] == 0


# --- reasons ---------------------------------------------------------------
def test_reasons_three_lines_all_api(seeded):
    from app.main import app
    c = TestClient(app)
    for i in range(1, 49):
        r = c.get(f"/restaurants/R{i:03d}").json()["reasons"]
        assert len(r) == 3 and all(line and "공직자" not in line for line in r)
    body = c.post("/recommend", json={"lat": 37.5663, "lng": 126.9779, "mood": ["가성비"], "limit": 5}).json()
    for it in body["items"]:
        assert len(it["reasons"]) == 3 and all("공직자" not in x for x in it["reasons"])


def test_reasons_good_price_not_a_designation():
    c = Candidate(id="X", name="x", genre="한식", price_band="~1만", moods=["가성비"], alcohol=False,
                  lat=37.56, lng=126.97, star=2.5, percentile=50)
    r = make_reasons(Scored(c, 100, 2.5), Query(lat=37.56, lng=126.97, mood=["가성비"]))
    assert "가성비 분위기" in r[1] and "착한가격" not in r[2]


# --- N+1 (가이드·착한가격 신호 포함 후에도 상수 쿼리) ------------------------------------
def test_no_n_plus_one_with_v21_signals(seeded):
    from app import service
    conn = appdb.connect(seeded)
    n = [0]
    conn.set_trace_callback(lambda s: n.__setitem__(0, n[0] + s.lstrip().upper().startswith("SELECT")))
    cands = service.candidates_near(conn, 37.5663, 126.9779, 5000)
    conn.set_trace_callback(None)
    assert len(cands) > 10 and n[0] <= 2
    assert any(c.guides for c in cands) and any("가성비" in c.moods for c in cands)


def test_migration_recorded_and_scan_skipped(seeded):
    assert sqlite3.connect(seeded).execute("PRAGMA user_version").fetchone()[0] == appdb.SCHEMA_VERSION
    conn = appdb.connect(seeded)
    seen = []
    conn.set_trace_callback(seen.append)
    appdb.init_schema(conn)
    conn.set_trace_callback(None)
    assert not any("partner" in s for s in seen)
