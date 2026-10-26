"""QA: 점수 모델 v2 (docs/01_planning_decision.md "점수 모델 v2") 스펙 대조·경계·회귀 검증.

xfail(strict=True) 는 확인된 결함(docs/qa/report_prior_v2.md)을 기록한 것 — 수정되면 XPASS 로 실패하므로 표시 제거.
"""
from __future__ import annotations

import math
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as appdb
from app.ingest.load_seed import load
from app.schemas import ScoreBreakdown, ScoreComponents
from app.scoring import prior
from app.scoring.recommend import Candidate, Query, Scored, make_reasons

NOW = date(2026, 10, 26)
REPO = Path(__file__).resolve().parents[2]


# --- 1. 식·상수 ----------------------------------------------------------------
def test_constants_match_spec():
    assert (prior.W_TENURE, prior.W_GOV, prior.W_HYGIENE, prior.W_DESIGNATION, prior.W_PARTNER) == (
        0.30, 0.25, 0.15, 0.10, 0.20)
    assert prior.TENURE_CAP_YEARS == 20 and prior.GOV_CAP == 30
    assert prior.HYGIENE_SCORES == {"매우우수": 1.0, "우수": 0.7, "좋음": 0.4}
    assert prior.PARTNER_NEUTRAL == 0.5
    assert (prior.SANCTION_UNIT, prior.SANCTION_CAP, prior.SANCTION_YEARS) == (0.05, 0.15, 3)
    assert (prior.W_AD, prior.AD_THRESHOLD, prior.AD_SPAN, prior.AD_FLOOR_RATIO, prior.AD_CONF_FULL_N) == (
        0.30, 0.15, 0.5, 0.5, 10)


def test_ad_keywords_exactly_spec():
    assert set(prior.AD_KEYWORDS) == {"체험단", "협찬", "제공받아", "원고료", "소정의"}  # 스펙 개정: '소정의' 포함


def test_tenure_formula():
    for yrs in (1, 5, 10, 19.5):
        start = date.fromordinal(NOW.toordinal() - round(yrs * 365.2425))
        assert prior.tenure_score(start, NOW) == pytest.approx(math.log1p(yrs) / math.log1p(20), abs=1e-3)
    assert prior.tenure_score("1990-01-01", NOW) == 1.0  # 20년 초과 cap
    assert prior.tenure_score(None, NOW) == 0.0


def test_gov_formula_and_cap():
    assert prior.gov_score(30) == pytest.approx(1.0)
    assert prior.gov_score(500) == 1.0
    assert prior.gov_score(5) == pytest.approx(math.log1p(5) / math.log1p(30))
    assert prior.gov_bonus(5) == pytest.approx(0.25 * math.log1p(5) / math.log1p(30))


def test_hygiene_designation_partner():
    assert [prior.hygiene_score(g) for g in ("매우우수", "우수", "좋음", None, "", "기타")] == [1, 0.7, 0.4, 0, 0, 0]
    assert prior.designation_score(["good_price"]) == 1.0
    assert prior.designation_score(["good_price", "century_store", "model_restaurant"]) == 1.0
    assert prior.designation_score([]) == 0.0 and prior.designation_score(["unknown"]) == 0.0
    assert prior.partner_score(None) == 0.5
    assert prior.partner_score(5.0) == 1.0 and prior.partner_score(1.0) == 0.0


def test_sanction_rule():
    assert prior.sanction_penalty(prior.recent_sanctions(["2025-01-01"], NOW)) == pytest.approx(0.05)
    assert prior.sanction_penalty(prior.recent_sanctions(["2025-01-01"] * 2, NOW)) == pytest.approx(0.10)
    assert prior.sanction_penalty(prior.recent_sanctions(["2025-01-01"] * 5, NOW)) == pytest.approx(0.15)  # 상한
    assert prior.recent_sanctions(["2020-01-01"], NOW) == 0  # 3년 초과


def test_ad_formula_conf_and_floor():
    assert prior.ad_conf_from_count(0) == 0 and prior.ad_conf_from_count(5) == 0.5
    assert prior.ad_conf_from_count(10) == 1 and prior.ad_conf_from_count(40) == 1
    assert prior.ad_penalty_raw(0.15, 1) == 0
    assert prior.ad_penalty_raw(0.40, 1) == pytest.approx(0.30 * 0.25 / 0.5)
    assert prior.ad_penalty_raw(0.90, 0.5) == pytest.approx(0.15)
    # 하한: 가점 합계 = partner 중립 0.1 → 감점 ≤ 0.05
    p = prior.prior_parts(now=NOW, ad_ratio=1.0, ad_conf=1.0)
    assert p.ad_penalty == pytest.approx(0.05) and p.prior_raw == pytest.approx(0.05)
    # 합계 일관성
    p = prior.prior_parts(now=NOW, opened_at="2010-01-01", gov_visits=4, hygiene_grade="우수",
                          designations=["safe_restaurant"], partner_rating=4.0, sanction_dates=["2025-05-01"],
                          ad_ratio=0.5, ad_conf=1.0)
    assert sum(p.components.values()) == pytest.approx(p.prior_raw)
    assert set(p.components) == set(prior.COMPONENT_KEYS)


def test_evidence_bands():
    assert [prior.evidence_level(n) for n in (0, 1, 2, 3, 7)] == ["low", "mid", "mid", "high", "high"]
    assert prior.prior_parts(now=NOW).evidence == "low"  # partner 결측 중립값은 신호 아님
    assert prior.prior_parts(now=NOW, hygiene_grade="좋음").evidence == "mid"
    assert prior.prior_parts(now=NOW, partner_rating=1.0).evidence == "mid"  # 제휴 값 존재 = 신호(기여 0 이어도)
    assert prior.prior_parts(now=NOW, hygiene_grade="좋음", gov_visits=1, opened_at="2020-01-01").evidence == "high"


# --- 2. 경계/엣지 ----------------------------------------------------------------
@pytest.mark.parametrize("bad", ["2030-01-01", "abcd", "2026-13-40", "", "   ", "0000-00-00", "2020/02/30"])
def test_tenure_future_or_invalid_is_zero(bad):
    assert prior.tenure_score(bad, NOW) == 0.0


def test_date_formats_accepted():
    for s in ("2016-10-26", "20161026", "2016.10.26", "2016/10/26", "2016-10-26T09:00:00"):
        assert prior.parse_date(s) == date(2016, 10, 26)


def test_gov_negative_or_null():
    assert prior.gov_score(-5) == 0.0 and prior.gov_score(None) == 0.0


def test_partner_out_of_range_clamped():
    assert prior.partner_score(-3) == 0.0 and prior.partner_score(9) == 1.0


def test_sanction_boundaries():
    assert prior.recent_sanctions(["2023-10-27"], NOW) == 1  # 3년 - 1일 → 포함
    assert prior.recent_sanctions(["2023-10-26"], NOW) == 1  # 정확히 3년 전 당일 → 포함 (스펙 개정)
    assert prior.recent_sanctions(["2023-10-25"], NOW) == 0  # 3년 + 1일 → 제외
    assert prior.recent_sanctions([NOW], NOW) == 1  # 당일 포함
    assert prior.recent_sanctions(["2027-01-01", None, "bad"], NOW) == 0  # 미래·결측·오류 제외
    assert prior.recent_sanctions(["2021-02-27"], date(2024, 2, 29)) == 0  # 윤일 기준일(3년 전 = 2/28)
    assert prior.recent_sanctions(["2021-02-28"], date(2024, 2, 29)) == 1


def test_zero_reviews_no_ad_penalty():
    assert prior.own_ad_stats([]) is None
    assert prior.pick_ad_signal(None, None) is None
    p = prior.prior_parts(now=NOW, ad_ratio=None)
    assert p.ad_penalty == 0 and p.components["ad"] == 0


def test_ad_keyword_basic_matching():
    assert prior.is_ad_text("업체로부터 제품을 제공받아 작성")
    assert prior.is_ad_text("[체험단] 맛있어요")
    assert prior.is_ad_text("소정의 원고료를 받아 작성") and prior.is_ad_text("협찬받아 작성했습니다")
    assert not prior.is_ad_text("내돈내산 맛집") and not prior.is_ad_text(None) and not prior.is_ad_text("")


@pytest.mark.parametrize("text", ["협찬 아님, 내돈내산", "체험단 아닙니다", "광고·협찬 없이 직접 결제", "원고료 받지 않았습니다"])
def test_ad_keyword_negation_not_ad(text):
    assert not prior.is_ad_text(text)


# --- 3. 마이그레이션 / 성능 ---------------------------------------------------------
@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    monkeypatch.setenv("JJINMAT_DB", str(path))
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    load(path)
    return path


def _downgrade_scores(path: Path) -> None:
    """v1 스키마(components/evidence 없음) 로 되돌림 — 기존 DB 재현."""
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE scores DROP COLUMN components")
    conn.execute("ALTER TABLE scores DROP COLUMN evidence")
    conn.commit()
    conn.close()


def test_migration_adds_columns_and_api_works(seeded):
    _downgrade_scores(seeded)
    from app.main import app
    c = TestClient(app)
    r = c.get("/restaurants/R003")
    assert r.status_code == 200
    b = r.json()["score_breakdown"]
    assert set(b["components"]) == set(prior.COMPONENT_KEYS)
    conn = sqlite3.connect(seeded)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(scores)")}
    assert {"components", "evidence"} <= cols
    assert c.post("/recommend", json={"lat": 37.5663, "lng": 126.9779}).status_code == 200


def test_migration_pre_recompute_not_misreported(seeded):
    from app.main import app
    c = TestClient(app)
    before = {f"R{i:03d}": c.get(f"/restaurants/R{i:03d}").json()["score_breakdown"]["evidence"] for i in range(1, 49)}
    _downgrade_scores(seeded)
    after = {k: c.get(f"/restaurants/{k}").json()["score_breakdown"]["evidence"] for k in before}
    assert after == before


def _count_queries(conn, fn):
    n = [0]
    conn.set_trace_callback(lambda s: n.__setitem__(0, n[0] + (s.lstrip().upper().startswith("SELECT"))))
    fn()
    conn.set_trace_callback(None)
    return n[0]


def test_no_n_plus_one(seeded):
    from app import service
    conn = appdb.connect(seeded)
    q_near = _count_queries(conn, lambda: service.candidates_near(conn, 37.5663, 126.9779, 3000))
    q_detail = _count_queries(conn, lambda: service.get_scored(conn, "R001"))
    regions = conn.execute("SELECT COUNT(DISTINCT IFNULL(sigungu_code,'∅')) FROM restaurants").fetchone()[0]
    q_rebuild = _count_queries(conn, lambda: service.rebuild_scores(conn, today=NOW))
    n_rest = conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0]
    assert q_near <= 2 and q_detail <= 2
    assert q_rebuild <= 1 + 4 * regions < n_rest  # 지역당 상수 쿼리, 가게 수 비례 아님


def test_signals_reload_idempotent(seeded):
    from app.ingest.csv_adapters import RestaurantSignalsCSVAdapter
    from app.ingest.load_seed import SEED_DIR
    load(seeded, [RestaurantSignalsCSVAdapter(SEED_DIR / "restaurant_signals.csv")], reset=False)
    conn = sqlite3.connect(seeded)
    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM restaurant_signals GROUP BY restaurant_id,kind,value,base_date"
        " HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup == 0


# --- 4. 문구 / reasons / 모바일 타입 ----------------------------------------------------
def test_reasons_three_lines_and_no_forbidden_word(seeded):
    from app.main import app
    c = TestClient(app)
    for i in range(1, 49):
        d = c.get(f"/restaurants/R{i:03d}").json()
        assert len(d["reasons"]) == 3 and all(d["reasons"])
        assert "공직자" not in " ".join(d["reasons"])
    for lat, lng in ((37.5663, 126.9779), (37.5, 127.03), (37.55, 126.92)):
        for it in c.post("/recommend", json={"lat": lat, "lng": lng, "radius_m": 3000}).json()["items"]:
            assert len(it["reasons"]) == 3 and "공직자" not in " ".join(it["reasons"])


def test_no_forbidden_word_in_product_code():
    hits = []
    for p in list((REPO / "backend" / "app").rglob("*.py")) + list((REPO / "mobile").glob("**/*.ts*")):
        if "node_modules" in p.parts:
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "공직자" in line and "금지" not in line:  # 금지 규칙 주석은 허용
                hits.append(f"{p}:{ln}")
    assert hits == []


def test_low_evidence_with_reviews_mentions_reviews():
    cand = Candidate(id="X", name="x", genre="한식", price_band="1~2만", moods=[], alcohol=False,
                     lat=37.5, lng=127.0, star=3.0, percentile=40, review_count=25, evidence="low")
    line3 = make_reasons(Scored(cand, 0, 3.0), Query(lat=37.5, lng=127.0))[2]
    assert "리뷰 25개" in line3


def _ts_fields(src: str, name: str) -> set[str]:
    body = re.search(r"export interface " + name + r"\s*(?:extends \w+\s*)?\{(.*?)\n\}", src, re.S).group(1)
    return set(re.findall(r"^\s*(\w+)\??:", body, re.M))


def test_mobile_types_match_api():
    src = (REPO / "mobile" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    assert _ts_fields(src, "ScoreBreakdown") == set(ScoreBreakdown.model_fields)
    assert _ts_fields(src, "ScoreComponents") == set(ScoreComponents.model_fields) == set(prior.COMPONENT_KEYS)
    assert re.search(r"export type Evidence = 'low' \| 'mid' \| 'high'", src)
