"""공공 선정·지정 목록 CSV → 가게 매칭 → restaurant_signals 적재 → 해당 시군구 점수 재계산.

    python -m app.ingest.load_designations <csv> [--db PATH] [--out-dir DIR] [--allow-michelin]

CSV 컬럼: name,address,lat,lng,kind,base_date,source (lat/lng 선택). kind = prior.SIGNAL_KINDS 중 지정·가이드 계열.
매칭 실패 행은 수기 검토용 data/out/unmatched_<source>.csv 로 출력(git 제외).
미슐랭(michelin_*) 은 법무 확인 전이라 기본 보류 → --allow-michelin 일 때만 적재.
중복 신호는 UNIQUE(restaurant_id,kind,value,base_date) + INSERT OR IGNORE 로 무시(재적재 멱등).
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema
from app.scoring import prior
from app.service import rebuild_scores

from .csv_adapters import DesignationListCSVAdapter
from .matcher import RestaurantIndex

OUT_DIR = BACKEND_DIR / "data" / "out"
# 목록형으로 들어오는 kind (위생등급·행정처분은 별도 출처)
UNMATCHED_COLUMNS = (*DesignationListCSVAdapter.COLUMNS, "reason")
MICHELIN_HOLD_REASON = "미슐랭: 법무 확인 전 적재 보류"
LIST_KINDS = (*prior.DESIGNATION_KINDS, prior.CENTURY_KIND, prior.GOOD_PRICE_KIND, *prior.GUIDE_SCORES)


def _safe(source: str | None) -> str:
    s = re.sub(r"[^\w가-힣.-]+", "_", source or "unknown").strip("_")
    return s or "unknown"


def _write_unmatched(out_dir: Path, rows: list[tuple[dict, str]]) -> list[Path]:
    by_src: dict[str, list[tuple[dict, str]]] = {}
    for raw, reason in rows:
        by_src.setdefault(_safe(raw.get("source")), []).append((raw, reason))
    paths = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for src, items in by_src.items():
        p = out_dir / f"unmatched_{src}.csv"
        # 화이트리스트(COLUMNS + reason) 고정: 원본의 추가 컬럼(대표자·전화 등 PII)은 폐기
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=UNMATCHED_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for raw, reason in items:
                w.writerow({**{k: raw.get(k, "") for k in DesignationListCSVAdapter.COLUMNS}, "reason": reason})
        paths.append(p)
    return paths


def load_designations(
    conn: sqlite3.Connection,
    csv_path: Path | str,
    out_dir: Path | str = OUT_DIR,
    allow_michelin: bool = False,
) -> dict:
    """반환: {"matched", "inserted", "unmatched", "unmatched_files", "regions"}."""
    recs = DesignationListCSVAdapter(csv_path).fetch()
    index = RestaurantIndex(conn)
    rows, unmatched, regions = [], [], set()
    for r in recs:
        kind = r["kind"]
        if kind not in LIST_KINDS:
            unmatched.append((r["_raw"], f"알 수 없는 kind: {kind}"))
            continue
        if kind in prior.MICHELIN_KINDS and not allow_michelin:
            unmatched.append((r["_raw"], MICHELIN_HOLD_REASON))
            continue
        rest, reason = index.match(r["name"], r["address"], r["lat"], r["lng"])
        if rest is None:
            unmatched.append((r["_raw"], reason))
            continue
        d = prior.parse_date(r["base_date"])
        rows.append((rest.id, kind, "지정", f"{r['name']} | {r['address'] or ''} ({reason})",
                     d.isoformat() if d else r["base_date"], r["source"]))
        regions.add(rest.sigungu_code)
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO restaurant_signals(restaurant_id,kind,value,detail,base_date,source) VALUES(?,?,?,?,?,?)",
        rows,
    )
    inserted = conn.total_changes - before
    conn.commit()
    for reg in regions:
        rebuild_scores(conn, reg)
    files = _write_unmatched(Path(out_dir), unmatched) if unmatched else []
    held = sum(1 for _, reason in unmatched if reason == MICHELIN_HOLD_REASON)
    return {"matched": len(rows), "inserted": inserted, "unmatched": len(unmatched),
            "unmatched_files": files, "regions": regions, "michelin_held": held}


def main() -> None:
    ap = argparse.ArgumentParser(description="공공 선정·지정 목록 적재(가게 매칭)")
    ap.add_argument("csv")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--allow-michelin", action="store_true", help="법무 확인 완료 시에만")
    args = ap.parse_args()
    conn = connect(args.db or db_path())
    init_schema(conn)
    res = load_designations(conn, args.csv, args.out_dir, args.allow_michelin)
    print(f"[ok]   매칭 {res['matched']}건 (신규 신호 {res['inserted']}건), 재계산 시군구 {len(res['regions'])}곳")
    for p in res["unmatched_files"]:
        print(f"[warn] 매칭 실패 → {p}")
    review = res["unmatched"] - res["michelin_held"]
    if review:
        print(f"[warn] 매칭 실패 {review}건 — 수기 검토 필요")
    if res["michelin_held"]:
        print(f"[info] 미슐랭 {res['michelin_held']}건 적재 보류(법무 확인 전)")
    conn.close()


if __name__ == "__main__":
    main()
