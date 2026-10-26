"""CSV 어댑터 4종. '#' 로 시작하는 줄은 주석(가상 데이터 표기 등)으로 무시."""
from __future__ import annotations

import csv
from pathlib import Path

from .base import Record, SourceAdapter


def read_csv(path: Path | str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#") and ln.strip()]
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(lines)]


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "y", "yes", "t", "o", "가능"}


def _float(v: str | None, default: float | None = None) -> float | None:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _int(v: str | None, default: int | None = None) -> int | None:
    f = _float(v)
    return int(f) if f is not None else default


class _CSVAdapter(SourceAdapter):
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def available(self) -> bool:
        return self.path.exists()


class RestaurantsCSVAdapter(_CSVAdapter):
    kind = "restaurants"
    name = "restaurants_csv"

    def fetch(self) -> list[Record]:
        out = []
        for r in read_csv(self.path):
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "genre": r["genre"],
                    "price_band": r["price_band"],
                    "moods": [m for m in r.get("moods", "").split("|") if m],
                    "alcohol": _bool(r.get("alcohol", "")),
                    "lat": float(r["lat"]),
                    "lng": float(r["lng"]),
                    "address": r.get("address") or None,
                    "updated_at": r.get("updated_at") or None,
                    "opened_at": r.get("opened_at") or None,
                }
            )
        return out


class ReviewStatsCSVAdapter(_CSVAdapter):
    kind = "review_stats"
    name = "review_stats_csv"

    def fetch(self) -> list[Record]:
        out = []
        for r in read_csv(self.path):
            out.append(
                {
                    "restaurant_id": r["restaurant_id"],
                    "ext_rating": _float(r.get("ext_rating")),
                    "ext_review_count": _int(r.get("ext_review_count"), 0),
                    "ad_ratio": _float(r.get("ad_ratio"), 0.0),
                    "ad_conf": _float(r.get("ad_conf"), 0.0),
                    "source": r.get("source") or None,
                    "updated_at": r.get("updated_at") or None,
                }
            )
        return out


class GovExpenseCSVAdapter(_CSVAdapter):
    """업무추진비 공개 내역. 화이트리스트 컬럼만 통과 → 개인 이름 등 PII 는 적재 전 제거."""

    kind = "gov_expense"
    name = "gov_expense_csv"
    ALLOWED = (
        "restaurant_id",
        "restaurant_name",
        "exec_date",
        "agency",
        "amount",
        "purpose",
        "source",
        "base_year",
    )
    # 참고용(화이트리스트 밖이라 어차피 제거됨)
    KNOWN_PII = ("official_name", "card_holder", "attendee_names", "user_name", "성명", "집행자", "사용자")

    def fetch(self) -> list[Record]:
        out = []
        for r in read_csv(self.path):
            rec: Record = {k: r.get(k) or None for k in self.ALLOWED}
            rec["amount"] = _int(rec["amount"])
            rec["base_year"] = _int(rec["base_year"])
            out.append(rec)
        return out


class RestaurantSignalsCSVAdapter(_CSVAdapter):
    """공공 신호: 위생등급·지정업소(모범/착한가격/안심/백년가게)·행정처분."""

    kind = "restaurant_signals"
    name = "restaurant_signals_csv"
    KINDS = ("hygiene_grade", "sanction", "model_restaurant", "good_price", "safe_restaurant", "century_store")

    def fetch(self) -> list[Record]:
        out = []
        for r in read_csv(self.path):
            if r.get("kind") not in self.KINDS:
                continue
            out.append({k: r.get(k) or None for k in ("restaurant_id", "kind", "value", "detail", "base_date", "source")})
        return out
