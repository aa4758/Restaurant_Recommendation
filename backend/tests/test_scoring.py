from datetime import date
from statistics import mean

from app.scoring import bayes, prior, strict
from app.scoring.recommend import Candidate, Query, make_reasons, recommend, rotate_ties, Scored


NOW = date(2026, 10, 1)


def test_gov_bonus_monotonic_and_capped():
    vals = [prior.gov_bonus(n) for n in range(0, 100)]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
    assert prior.gov_bonus(0) == 0
    assert abs(prior.gov_bonus(prior.GOV_CAP) - prior.W_GOV) < 1e-9
    assert prior.gov_bonus(1000) == prior.gov_bonus(prior.GOV_CAP)  # cap 300회 (v2.2)


def test_tenure_capped_at_20y_and_uses_now():
    assert prior.tenure_score(None, NOW) == 0
    assert prior.tenure_score("2030-01-01", NOW) == 0  # 미래 인허가일 → 0
    assert prior.tenure_score("2006-10-01", NOW) == 1.0  # 20년
    assert prior.tenure_score("1980-01-01", NOW) == 1.0  # 20년 초과도 동일
    assert prior.tenure_score("20160101", NOW) < 1.0  # YYYYMMDD 형식
    vals = [prior.tenure_score(f"{y}-10-01", NOW) for y in range(2026, 2000, -1)]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
    # 기준일이 다르면 결과도 달라짐(결정적: 현재 시각 비의존)
    assert prior.tenure_score("2020-01-01", date(2021, 1, 1)) < prior.tenure_score("2020-01-01", NOW)
    p = prior.prior_parts(now=NOW, opened_at="2000-01-01")
    assert abs(p.components["tenure"] - prior.W_TENURE) < 1e-9


def test_hygiene_mapping():
    assert prior.hygiene_score("매우우수") == 1.0
    assert prior.hygiene_score("매우 우수") == 1.0
    assert prior.hygiene_score("우수") == 0.7
    assert prior.hygiene_score("좋음") == 0.4
    assert prior.hygiene_score(None) == 0 and prior.hygiene_score("미지정") == 0
    p = prior.prior_parts(now=NOW, hygiene_grade="우수")
    assert abs(p.components["hygiene"] - prior.W_HYGIENE * 0.7) < 1e-9


def test_designation_duplicates_count_once():
    one = prior.prior_parts(now=NOW, designations=["model_restaurant"])
    many = prior.prior_parts(now=NOW, designations=["origin_label_excellent", "model_restaurant", "safe_restaurant"])
    assert one.components["designation"] == many.components["designation"] == prior.W_DESIGNATION
    assert prior.designation_score([]) == 0 and prior.designation_score(["sanction"]) == 0


def test_partner_missing_is_neutral():
    p = prior.prior_parts(now=NOW)
    assert abs(p.components["reputation"] - prior.W_REPUTATION * 0.4) < 1e-9
    assert prior.partner_score(5.0) == 1.0 and prior.partner_score(1.0) == 0.0
    assert prior.partner_score(3.0) == 0.5


def test_sanction_recent_3y_capped():
    assert prior.sanction_penalty(1) == 0.05
    assert prior.sanction_penalty(3) == 0.15
    assert prior.sanction_penalty(10) == 0.15  # 상한
    assert prior.recent_sanctions(["2023-10-02", "2023-09-30", None, "2027-01-01"], NOW) == 1  # 3년 밖·미상·미래 무시
    old = prior.prior_parts(now=NOW, sanction_dates=["2020-01-01", "2019-05-05"])
    assert old.components["sanction"] == 0
    many = prior.prior_parts(now=NOW, sanction_dates=["2026-01-01"] * 5)
    assert abs(many.components["sanction"] + prior.SANCTION_CAP) < 1e-9
    base = prior.prior_parts(now=NOW)
    assert abs(base.prior_raw - many.prior_raw - prior.SANCTION_CAP) < 1e-9


def test_ad_penalty_monotonic_conf_and_floor():
    assert prior.ad_penalty_raw(0.1, 1.0) == 0  # 임계값 이하 무감점
    pens = [prior.ad_penalty_raw(r / 100, 1.0) for r in range(0, 101)]
    assert all(a <= b for a, b in zip(pens, pens[1:]))
    assert prior.ad_penalty_raw(0.9, 0.5) < prior.ad_penalty_raw(0.9, 1.0)  # 신뢰도 반영
    # 하한: 감점 ≤ 가점 합계의 50% (가점 = 외부 평판 중립 0.08 뿐)
    p = prior.prior_parts(now=NOW, ad_ratio=1.0, ad_conf=1.0)
    plus = sum(v for v in p.components.values() if v > 0)
    assert abs(p.ad_penalty - plus * prior.AD_FLOOR_RATIO) < 1e-9
    assert p.prior_raw >= plus * (1 - prior.AD_FLOOR_RATIO) - 1e-9
    assert p.components["ad"] == -p.ad_penalty
    assert prior.prior_parts(now=NOW, ad_ratio=None).ad_penalty == 0


def test_ad_conf_and_own_review_keywords():
    assert prior.ad_conf_from_count(0) == 0
    assert prior.ad_conf_from_count(5) == 0.5
    assert prior.ad_conf_from_count(10) == 1.0 and prior.ad_conf_from_count(50) == 1.0
    for kw in ("체험단", "협찬", "제공받아", "원고료", "소정의"):
        assert prior.is_ad_text(f"맛있어요 {kw} 문구")
    assert not prior.is_ad_text("내돈내산") and not prior.is_ad_text(None)
    ratio, conf = prior.own_ad_stats(["체험단으로 방문", "그냥 맛있음", "협찬", "굿", None])
    assert ratio == 2 / 5 and conf == 0.5
    assert prior.own_ad_stats([]) is None
    # 신뢰도 높은 쪽 사용
    assert prior.pick_ad_signal((0.4, 0.5), (0.1, 0.9)) == (0.1, 0.9)
    assert prior.pick_ad_signal((0.4, 1.0), (0.1, 0.9)) == (0.4, 1.0)
    assert prior.pick_ad_signal(None, None) is None


def test_evidence_levels():
    assert prior.prior_parts(now=NOW).evidence == "low"  # 제휴 중립값은 신호 아님
    assert prior.prior_parts(now=NOW, partner_rating=4.0).evidence == "mid"
    assert prior.prior_parts(now=NOW, gov_visits=3, hygiene_grade="좋음").evidence == "mid"
    assert prior.prior_parts(now=NOW, gov_visits=3, hygiene_grade="좋음", designations=["safe_restaurant"]).evidence == "high"
    assert prior.prior_parts(now=NOW, sanction_dates=["2019-01-01"]).evidence == "low"  # 3년 밖 처분 무시
    assert [prior.evidence_level(n) for n in (0, 1, 2, 3, 7)] == ["low", "mid", "mid", "high", "high"]


def test_components_sum_to_prior_raw():
    p = prior.prior_parts(now=NOW, opened_at="2010-03-01", gov_visits=7, hygiene_grade="매우우수",
                          designations=["model_restaurant"], partner_rating=4.2, sanction_dates=["2025-01-01"],
                          ad_ratio=0.4, ad_conf=0.8)
    assert set(p.components) == set(prior.COMPONENT_KEYS)
    assert abs(sum(p.components.values()) - p.prior_raw) < 1e-9
    assert p.gov_bonus == p.components["gov"]


def test_equal_prior_gives_equal_star():
    same = dict(now=NOW, opened_at="2015-01-01", hygiene_grade="우수")
    raws = [prior.prior_raw(**same), prior.prior_raw(**same), prior.prior_raw(now=NOW, gov_visits=5)]
    stars = strict.strict_map(raws)
    assert stars[0] == stars[1] and stars[2] != stars[0]


def test_strict_map_mean_and_top_share():
    stars = strict.strict_map(list(range(10000)))  # v2.3: 5.0 = 상위 약 0.1%, 4.5 이상 약 0.7%
    assert abs(mean(stars) - 2.5) < 0.05
    five = sum(s >= 4.95 for s in stars) / len(stars)  # 화면 표시 5.0(소수 첫째 자리)
    assert 0.0005 <= five <= 0.002
    top = sum(s >= 4.5 for s in stars) / len(stars)
    assert 0.004 <= top <= 0.01
    assert all(0 <= s <= 5 for s in stars)
    assert stars == sorted(stars)  # 단조


def test_strict_map_ties_equal():
    assert len(set(strict.strict_map([1, 1, 1]))) == 1


def test_top_percents():
    pcts = strict.top_percents([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert pcts[9] == 10 and pcts[0] == 100
    assert strict.top_percents([3, 3]) == [100, 100]  # 동점은 묶음의 최저 순위
    assert strict.top_percents([5, 3, 3]) == [34, 100, 100]
    assert strict.top_percents([]) == []


def test_bayes_half_at_k():
    assert bayes.final_star(2.0, None, 0) == 2.0
    assert bayes.final_star(2.0, 4.0, bayes.K) == 3.0  # n=20 → 50:50
    assert bayes.prior_weight(bayes.K) == 0.5


def _cand(i, **kw):
    base = dict(id=f"C{i}", name=f"n{i}", genre="한식", price_band="1~2만", moods=["조용한"],
                alcohol=False, lat=37.5663, lng=126.9779, star=2.5, percentile=50)
    base.update(kw)
    return Candidate(**base)


def test_relax_order_and_alcohol_never_relaxed():
    far = 37.5663 + 0.015  # 약 1.7km
    cands = [_cand(1, genre="중식", lat=far), _cand(2, genre="중식", lat=far), _cand(3, genre="중식", lat=far),
             _cand(4, alcohol=True)]
    q = Query(lat=37.5663, lng=126.9779, radius_m=1000, genre=["한식"], mood=["조용한"], alcohol="no")
    items, relaxed = recommend(cands, q, day=date(2026, 1, 1))
    assert relaxed == ["mood", "distance", "genre"]  # 지정된 조건만, 정해진 순서로
    assert all(not s.cand.alcohol for s in items)  # 음주 조건은 유지


def test_alcohol_unknown_excluded_from_yes_and_no():
    """음주 미확인(None)은 '음주 불가'·'음주 가능' 어느 쪽에도 넣지 않음(2026-11-12)."""
    cands = [_cand(1, alcohol=None), _cand(2, alcohol=False), _cand(3, alcohol=True)]
    q = dict(lat=37.5663, lng=126.9779, radius_m=1000)
    ids = lambda a: {s.cand.id for s in recommend(cands, Query(**q, alcohol=a), day=date(2026, 1, 1))[0]}
    assert ids("no") == {"C2"}
    assert ids("yes") == {"C3"}
    assert ids("any") == {"C1", "C2", "C3"}


def test_no_relax_when_enough():
    cands = [_cand(i) for i in range(5)]
    items, relaxed = recommend(cands, Query(lat=37.5663, lng=126.9779), day=date(2026, 1, 1))
    assert relaxed == [] and len(items) == 3
    assert all(len(s.reasons) == 3 for s in items)


def test_rotate_ties_deterministic_per_day():
    items = [Scored(_cand(i), 0, 3.0) for i in range(6)]
    a = [s.cand.id for s in rotate_ties(items, date(2026, 1, 1))]
    b = [s.cand.id for s in rotate_ties(items, date(2026, 1, 1))]
    assert a == b and sorted(a) == sorted(s.cand.id for s in items)
    orders = {tuple(s.cand.id for s in rotate_ties(items, date(2026, 1, d))) for d in range(1, 11)}
    assert len(orders) > 1  # 날짜별 로테이션


def test_reasons_no_ad_claim_without_stats():
    q = Query(lat=37.5663, lng=126.9779)
    s = Scored(_cand(1), 0, 2.5)
    assert "광고" not in make_reasons(s, q)[2]  # 통계 없으면 광고 비율 주장 금지
    s = Scored(_cand(2, ad_penalty=0.0), 0, 2.5)
    assert "광고" in make_reasons(s, q)[2]


def test_reasons_public_facts_and_low_evidence():
    q = Query(lat=37.5663, lng=126.9779)
    s = Scored(_cand(3, tenure_years=12, hygiene_grade="매우우수", designations=["모범음식점"], evidence="high"), 0, 2.5)
    line3 = make_reasons(s, q)[2]
    assert "업력 12년" in line3 and "위생등급 매우우수" in line3 and "모범음식점 지정" in line3
    s = Scored(_cand(4, evidence="low", ad_penalty=0.0), 0, 2.5)
    r = make_reasons(s, q)
    assert len(r) == 3 and r[2].startswith("근거 부족")
    s = Scored(_cand(5, gov_visits=3, gov_source="샘플", tenure_years=30, evidence="mid"), 0, 2.5)
    line3 = make_reasons(s, q)[2]
    assert "업무추진비 기록 3회" in line3 and "업력 30년" in line3 and "공직자" not in line3
