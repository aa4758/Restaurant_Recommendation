from datetime import date
from statistics import mean

from app.scoring import bayes, prior, strict
from app.scoring.recommend import Candidate, Query, recommend, rotate_ties, Scored


def test_gov_bonus_monotonic_and_capped():
    vals = [prior.gov_bonus(n) for n in range(0, 100)]
    assert all(a <= b for a, b in zip(vals, vals[1:]))
    assert prior.gov_bonus(0) == 0
    assert abs(prior.gov_bonus(prior.GOV_CAP) - prior.W_GOV) < 1e-9
    assert prior.gov_bonus(1000) == prior.gov_bonus(prior.GOV_CAP)


def test_ad_penalty_monotonic_and_floor():
    assert prior.ad_penalty_raw(0.1, 1.0) == 0  # 임계값 이하 무감점
    pens = [prior.ad_penalty_raw(r / 100, 1.0) for r in range(0, 101)]
    assert all(a <= b for a, b in zip(pens, pens[1:]))
    assert prior.ad_penalty_raw(0.9, 0.5) < prior.ad_penalty_raw(0.9, 1.0)  # 신뢰도 반영
    p = prior.prior_parts(0.2, 0, 1.0, 1.0)  # 감점이 floor 에 걸리는 경우
    assert p.prior_raw >= 0.2 * prior.AD_FLOOR_RATIO - 1e-9


def test_strict_map_mean_and_top_share():
    stars = strict.strict_map(list(range(1000)))
    assert abs(mean(stars) - 2.5) < 0.05
    top = sum(s >= 4.5 for s in stars) / len(stars)
    assert 0.02 <= top <= 0.04
    assert all(0 <= s <= 5 for s in stars)
    assert stars == sorted(stars)  # 단조


def test_strict_map_ties_equal():
    assert len(set(strict.strict_map([1, 1, 1]))) == 1


def test_top_percent():
    pop = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert strict.top_percent(10, pop) == 10
    assert strict.top_percent(1, pop) == 100


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
    assert relaxed == ["distance", "mood", "genre"]  # 지정된 조건만, 정해진 순서로
    assert all(not s.cand.alcohol for s in items)  # 음주 조건은 유지


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
