"""상가(상권)정보 CSV → 기존 restaurants(인허가 기반)에 sbiz_id·업종 소분류(sbiz_category) 연결.

    python -m app.ingest.link_sbiz [csv...] [--dry-run] [--db PATH]     # csv 생략 시 data/raw/sbiz/*.csv

- 신규 가게는 만들지 않는다(가게 뼈대는 인허가). 연결만 하므로 점수·장르는 바뀌지 않음(재계산 없음).
- 매칭: matcher(상호 + 도로명주소 | 50m, open 우선, 복수 = ambiguous). 상호는 '상호명 지점명'.
- 한 가게에 상가 여러 건이 맞으면 먼저 온 1건만(나머지는 '중복'). 이미 다른 가게에 붙은 sbiz_id 는 옮긴다.
- 재실행 멱등(같은 sbiz_id·소분류로 다시 UPDATE). --dry-run: SAVEPOINT 롤백, 통계만.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema

from .matcher import RestaurantIndex
from .sbiz import SbizStoresCSVAdapter

RAW_DIR = BACKEND_DIR / "data" / "raw" / "sbiz"


def link_sbiz(conn: sqlite3.Connection, csv_paths, dry_run: bool = False) -> dict:
    idx = RestaurantIndex(conn)
    stats: Counter = Counter()
    linked: dict[str, tuple[str, str | None]] = {}  # restaurant_id → (sbiz_id, 소분류)
    for path in csv_paths:
        for r in SbizStoresCSVAdapter(path).fetch():
            stats["rows"] += 1
            name = f"{r['name']} {r['branch']}" if r["branch"] else r["name"]
            hit, reason = idx.match(name, r["address"], r["lat"], r["lng"])
            if hit is None:
                stats[f"미매칭 · {reason}"] += 1
            elif hit.id in linked:
                stats["중복(같은 가게에 상가 여러 건)"] += 1
            else:
                linked[hit.id] = (r["sbiz_id"], r["genre_detail"])
                stats[f"매칭 · {reason}"] += 1
    conn.execute("SAVEPOINT link_sbiz")
    for rid, (sid, cat) in linked.items():
        conn.execute("UPDATE restaurants SET sbiz_id=NULL WHERE sbiz_id=? AND id<>?", (sid, rid))
        conn.execute("UPDATE restaurants SET sbiz_id=?, sbiz_category=? WHERE id=?", (sid, cat, rid))
    conn.execute("ROLLBACK TO link_sbiz" if dry_run else "RELEASE link_sbiz")
    if dry_run:
        conn.execute("RELEASE link_sbiz")
    conn.commit()
    return {**stats, "linked": len(linked)}


def main() -> None:
    ap = argparse.ArgumentParser(description="상가(상권)정보 → 기존 가게 sbiz_id·업종 소분류 연결")
    ap.add_argument("csv", nargs="*")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 통계만")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    a = ap.parse_args()
    paths = [Path(p) for p in a.csv] or sorted(RAW_DIR.glob("*.csv"))
    conn = connect(a.db or db_path())
    init_schema(conn)
    res = link_sbiz(conn, paths, a.dry_run)
    total = conn.execute("SELECT COUNT(*), COUNT(sbiz_category) FROM restaurants WHERE status='open'").fetchone()
    print(f"[{'dry-run' if a.dry_run else 'ok'}] {a.db or db_path()} · 파일 {len(paths)}개 · 상가 음식점 {res.pop('rows', 0):,}행"
          f" → 가게 {res.pop('linked'):,}곳 연결 (영업 중 {total[0]:,}곳 중 소분류 있음 {total[1]:,})")
    for k, v in sorted(res.items(), key=lambda kv: -kv[1]):
        print(f"       {k}: {v:,}")


if __name__ == "__main__":
    main()
