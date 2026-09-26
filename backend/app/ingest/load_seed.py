"""시드 CSV → SQLite 적재.  사용: python -m app.ingest.load_seed [--db PATH] [--seed-dir DIR]"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema

from .base import SourceAdapter
from .csv_adapters import GovExpenseCSVAdapter, RestaurantsCSVAdapter, ReviewStatsCSVAdapter
from .kakao import KakaoLocalAdapter

SEED_DIR = BACKEND_DIR / "data" / "seed"


def default_adapters(seed_dir: Path = SEED_DIR) -> list[SourceAdapter]:
    return [
        RestaurantsCSVAdapter(seed_dir / "restaurants.csv"),
        KakaoLocalAdapter(),  # KAKAO_REST_KEY 없으면 skip
        ReviewStatsCSVAdapter(seed_dir / "review_stats.csv"),
        GovExpenseCSVAdapter(seed_dir / "gov_expense.csv"),
    ]


def _load_restaurants(conn: sqlite3.Connection, recs: list[dict]) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO restaurants(id,name,genre,price_band,moods,alcohol,lat,lng,address,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            (r["id"], r["name"], r["genre"], r["price_band"], "|".join(r["moods"]), int(r["alcohol"]),
             r["lat"], r["lng"], r.get("address"), r.get("updated_at"))
            for r in recs
        ],
    )
    return len(recs)


def _load_review_stats(conn: sqlite3.Connection, recs: list[dict]) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO review_stats(restaurant_id,ext_rating,ext_review_count,ad_ratio,ad_conf,source,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        [
            (r["restaurant_id"], r["ext_rating"], r["ext_review_count"], r["ad_ratio"], r["ad_conf"],
             r.get("source"), r.get("updated_at"))
            for r in recs
        ],
    )
    return len(recs)


def _load_gov(conn: sqlite3.Connection, recs: list[dict]) -> int:
    by_name = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM restaurants")}
    ids = set(by_name.values())
    rows = []
    for r in recs:
        rid = r.get("restaurant_id") or by_name.get(r.get("restaurant_name") or "")
        if rid not in ids:
            continue  # 매칭 실패 레코드는 버림
        rows.append((rid, r.get("exec_date"), r.get("agency"), r.get("amount"), r.get("purpose"),
                     r.get("source"), r.get("base_year")))
    conn.executemany(
        "INSERT INTO gov_expense(restaurant_id,exec_date,agency,amount,purpose,source,base_year) VALUES(?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


LOADERS = {"restaurants": _load_restaurants, "review_stats": _load_review_stats, "gov_expense": _load_gov}


def load(db: Path | str | None = None, adapters: list[SourceAdapter] | None = None, reset: bool = True) -> dict[str, int]:
    target = Path(db) if db else db_path()
    if reset and target.exists():
        target.unlink()
    conn = connect(target)
    init_schema(conn)
    counts: dict[str, int] = {}
    for ad in adapters if adapters is not None else default_adapters():
        if not ad.available():
            print(f"[skip] {ad.name}: 사용 불가(키 미설정 또는 파일 없음)")
            continue
        n = LOADERS[ad.kind](conn, ad.fetch())
        counts[ad.name] = n
        print(f"[ok]   {ad.name}: {n}건")
    conn.commit()
    conn.close()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="시드 데이터 적재")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--seed-dir", default=str(SEED_DIR))
    args = ap.parse_args()
    load(args.db, default_adapters(Path(args.seed_dir)))
    print(f"DB: {args.db or db_path()}")


if __name__ == "__main__":
    main()
