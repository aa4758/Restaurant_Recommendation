"""찐맛 export → 상호 정리 → 음식점 × 기관 방문 횟수 표(검토용). export 원본은 읽기만 한다.

- 선물·격려품 구매, 음식점 아닌 곳(전시관·회의실·주무관 이름 칸)은 버림.
- '가나식당 등 2개소' → 첫 가게, 'A, B' → 음식점 규칙에 걸리는 가게만(없으면 첫 가게), 주소·층·호수·잘린 괄호 제거.
- 띄어쓰기만 다른 이름은 하나로(가장 흔한 표기). 지역이 다른 동명 가게는 합쳐진다(이름이 키).
- gov_score: 찐맛 prior v2.1 의 업무추진비 항 min(log1p(방문수)/log1p(30), 1) (`backend/app/scoring/prior.py` GOV_CAP).
  단, 1회 방문은 0점(2026-10-29 사용자 결정 — 재방문 근거 없음). 앱 prior 는 그대로.
"""
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.phase5_merge.normalize import categorize, normalize_vendor

GOV_CAP = 30
GIFT = re.compile(r"격려품|기념품|선물|상품권|화환|답례품")
NOT_PLACE = re.compile(r"주무관|회의실|전시관|문화관|전수관|공예|직매장|보호작업장")
MULTI = re.compile(r"\s*(등\s*\d*\s*(개소|곳|개업체|개)?|\d+\s*개소)\s*$")
ADDR = re.compile(r"(\S+[시구군]\s)?\S+(로|길)\s\d+(-\d+)?|\d+층|\d+([.,]\d+)?호(?![점집])")


def clean(name: str) -> list[str]:
    n = unicodedata.normalize("NFKC", name)
    n = re.sub(r"\([^)]*$", "", n)  # 잘린 괄호: '닭장수 김밥(성신여'
    n = MULTI.sub("", n)
    parts = [normalize_vendor(ADDR.sub(" ", p)) for p in n.split(",")]
    parts = [p for p in parts if p and not re.fullmatch(r"[\d\s\-.]+", p)]
    if len(parts) > 1:
        # ponytail: 규칙에 안 걸리는 음식점(unknown)은 버려짐 — 필요하면 동명 단독 상호 존재 여부로 보강
        parts = [p for p in parts if categorize(p, "") == "restaurant"] or parts[:1]
    return parts


def gov_score(visits: int) -> float:
    if visits <= 1:
        return 0.0
    return min(math.log1p(visits) / math.log1p(GOV_CAP), 1.0)


def pivot(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """export 행 → (정리된 행, 음식점 × 기관 방문 횟수 표)."""
    d = d[~d["purpose"].str.contains(GIFT) & ~d["restaurant_name"].str.contains(NOT_PLACE)].copy()
    d["restaurant_name"] = d["restaurant_name"].map(clean)
    d = d.explode("restaurant_name").dropna(subset=["restaurant_name"])
    key = d["restaurant_name"].str.replace(" ", "")
    shown = d.groupby(key)["restaurant_name"].agg(lambda s: s.value_counts().index[0])
    d["restaurant_name"] = key.map(shown)
    p = pd.crosstab(d["restaurant_name"], d["agency"])
    total = p.sum(axis=1)
    p.insert(0, "gov_score", total.map(gov_score).round(4))
    p.insert(0, "total_visits", total)
    return d, p.sort_values(["total_visits", "restaurant_name"], ascending=[False, True])


def run(cfg: dict) -> int:
    src = Path(cfg["jjinmat_export"]["path"])
    d = pd.read_csv(src, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    rows, p = pivot(d)
    rows.to_csv(src.with_name("gov_expense_for_jjinmat_clean.csv"), index=False, encoding="utf-8-sig")
    p.to_csv(src.with_name("gov_expense_by_restaurant.csv"), encoding="utf-8-sig")
    print(f"음식점 {len(p):,}곳 · 기관 {p.shape[1] - 2} · 방문 {len(rows):,}건(export {len(d):,}행)", flush=True)
    return len(p)
