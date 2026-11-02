"""추천 제외 가게: 구내식당·급식과 회사명 상호(2026-11-02 사용자 결정, docs/01 '추천 제외 상호').

restaurants.exclude_reason 에 기록 → 점수 계산(service._region_rows)에서 빠짐 → 추천·상세·검색에 안 나옴.
원본 행은 지우지 않음(규칙을 바꾸면 다시 실행하면 됨). 인허가 재적재 뒤에도 다시 실행.

    python -m app.exclude            # 규칙 적용 + 점수 재계산
    python -m app.exclude --dry-run  # 건수·예시만
"""
from __future__ import annotations

import argparse
import re
import sqlite3

# 구내식당·급식·위탁급식('함바그'(햄버그)는 제외 안 함)
CAFETERIA = re.compile(r"구내식당|사내식당|직원식당|교직원식당|학생식당|기숙사식당|급식|함바(?!그)|푸드서비스|케이터링")
# 회사·법인 표기
CORPORATE = re.compile(r"\(주\)|\(株\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\(재\)|사단법인|재단법인|\(합\)|합자회사|협동조합|농업회사법인|영농조합")


def reason(name: str) -> str | None:
    if CAFETERIA.search(name):
        return "cafeteria"
    if CORPORATE.search(name):
        return "corporate"
    return None


def apply(conn: sqlite3.Connection, dry_run: bool = False) -> dict[str, int]:
    rows = conn.execute("SELECT id, name, exclude_reason FROM restaurants").fetchall()
    changes = [(reason(r[1]), r[0]) for r in rows if reason(r[1]) != r[2]]
    counts: dict[str, int] = {}
    for rs, _ in changes:
        counts[rs or "restored"] = counts.get(rs or "restored", 0) + 1
    if not dry_run and changes:
        conn.executemany("UPDATE restaurants SET exclude_reason=? WHERE id=?", changes)
        conn.commit()
    return counts


def main() -> None:
    from app import db
    from app.service import rebuild_scores

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    conn = db.connect()
    db.init_schema(conn)
    counts = apply(conn, a.dry_run)
    total = conn.execute("SELECT exclude_reason, COUNT(*) FROM restaurants WHERE status='open' AND exclude_reason IS NOT NULL"
                         " GROUP BY 1").fetchall()
    print(f"[exclude] 변경 {counts}, 현재 제외(영업 중) {dict(total)}")
    if not a.dry_run and counts:
        print(f"[exclude] 점수 재계산 {rebuild_scores(conn)}건")


if __name__ == "__main__":
    main()
