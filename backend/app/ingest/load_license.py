"""인허가(일반·휴게음식점) CSV → 기존 restaurants 매칭 → 폐업·일반/휴게·업력 반영 → 해당 시군구 점수 재계산.

    python -m app.ingest.load_license <csv...> [--crs EPSG:5174] [--calibrate] [--dry-run] [--db PATH] [--out-dir DIR]

- --calibrate: 상호 + 도로명주소로 확실히(후보 1곳) 매칭되는 표본(최대 200)의 거리 중앙값을 후보 CRS 별로
  계산해 가장 작은 CRS 를 보고하고 종료(적재 안 함). 적재 전에 먼저 실행.
- 매칭: license_id 일치 → 없으면 matcher(상호 + 도로명주소 | 50m, open 우선, 복수 = ambiguous).
- 같은 가게에 인허가 여러 건(폐업 후 재개업): 영업 중 > 최신 인허가일자 > 최신 갱신일 1건만 반영
  → 폐업 행이 영업 중 가게를 closed 로 덮지 않음.
- 미매칭 + 영업 중 + 좌표 있음 → 신규 가게 L{관리번호}. 미매칭 폐업은 무시.
  모호·좌표 없음 미매칭 → data/out/unmatched_license.csv (화이트리스트 컬럼 + reason, PII 없음).
- license_id UNIQUE → 재적재 멱등. --dry-run: DB 변경 롤백·재계산 생략(통계·unmatched 파일만).
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import statistics
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema
from app.scoring.recommend import haversine_m
from app.service import rebuild_scores

from .license import (
    CANDIDATE_CRS,
    DEFAULT_CRS,
    REST_TYPE,
    LicenseCSVAdapter,
    is_excluded,
    map_genre,
    tm_to_wgs84,
)
from .matcher import RestaurantIndex, _sido, addresses_match, normalize_name, normalize_road_address

OUT_DIR = BACKEND_DIR / "data" / "out"
UNMATCHED_FILE = "unmatched_license.csv"
# 화이트리스트: 사업장 정보만(대표자 등 PII·전화 제외)
UNMATCHED_COLUMNS = ("license_id", "license_type", "name", "biz_type", "status_raw", "opened_at", "closed_at",
                     "address_road", "address_jibun", "x", "y", "reason")
CALIBRATE_SAMPLE = 200


def read_records(paths, crs: str = DEFAULT_CRS) -> tuple[list[dict], list[str]]:
    recs, pii = [], []
    for p in paths:
        ad = LicenseCSVAdapter(p, crs)
        recs.extend(ad.fetch())
        pii.extend(f"{Path(p).name}:{h}" for h in ad.pii_dropped)
    return recs, pii


# --- calibrate ---------------------------------------------------------------
def calibrate(conn: sqlite3.Connection, recs: list[dict], candidates=CANDIDATE_CRS,
              sample: int = CALIBRATE_SAMPLE) -> dict:
    """반환: {"n": 표본 수, "medians": {crs: 중앙값 m}, "best": crs | None}."""
    index = RestaurantIndex(conn)
    pairs = []
    for r in recs:
        if not (r["x"] and r["y"] and r["address_road"]) or is_excluded(r["biz_type"]):
            continue
        hits = [c for c in index.name_candidates(r["name"]) if addresses_match(r["address_road"], c.address)]
        if len(hits) == 1:
            pairs.append((r["x"], r["y"], hits[0]))
            if len(pairs) >= sample:
                break
    medians = {}
    for crs in candidates:
        ds = []
        for x, y, rest in pairs:
            ll = tm_to_wgs84(x, y, crs)
            if ll:
                ds.append(haversine_m(ll[0], ll[1], rest.lat, rest.lng))
        if ds:
            medians[crs] = round(statistics.median(ds), 1)
    best = min(medians, key=medians.get) if medians else None
    return {"n": len(pairs), "medians": medians, "best": best}


# --- 적재 ----------------------------------------------------------------------
def _priority(r: dict) -> tuple:
    """같은 가게 다중 인허가 중 반영할 1건: 영업 중 > 최신 인허가일자 > 최신 갱신일 > 관리번호."""
    return (r["status"] == "open", r["opened_at"] or "", r["data_updated"] or "", r["license_id"])


def _region_map(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for sido, gu, code in conn.execute(
        "SELECT DISTINCT sido, sigungu, sigungu_code FROM restaurants WHERE sigungu_code IS NOT NULL"
    ):
        s = _sido((sido or "").strip()) or ""
        g = re.sub(r"\s+", "", gu or "")
        if g:
            out.setdefault((s, g), code)
    return out


def parse_region(addr: str | None) -> tuple[str | None, str | None, str | None]:
    """주소 → (시도 원문, 시군구 원문, 시도 약칭). '경기도 성남시 분당구 …' → ('경기도', '성남시 분당구', '경기')."""
    toks = (addr or "").split()
    if not toks:
        return None, None, None
    short = _sido(toks[0])
    rest = toks[1:] if short else toks
    gus = []
    for t in rest:
        if re.search(r"(시|군|구)$", t) and not re.search(r"(로|길)$", t):
            gus.append(t)
        else:
            break
    return (toks[0] if short else None), (" ".join(gus) or None), short


def _sigungu_code(regions: dict, addr: str | None) -> tuple[str | None, str | None, str | None]:
    sido, gu, short = parse_region(addr)
    if not gu:
        return sido, None, None
    parts = gu.split()
    for key in ("".join(parts), parts[-1]):
        code = regions.get((short or "", key))
        if code is None and not short:
            code = next((c for (s, g), c in regions.items() if g == key), None)
        if code:
            return sido, gu, code
    return sido, gu, None


def _write_unmatched(out_dir: Path, rows: list[tuple[dict, str]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / UNMATCHED_FILE
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=UNMATCHED_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for rec, reason in rows:
            w.writerow({**{k: rec.get(k) if rec.get(k) is not None else "" for k in UNMATCHED_COLUMNS[:-1]},
                        "reason": reason})
    return p


def load_license(conn: sqlite3.Connection, csv_paths, crs: str = DEFAULT_CRS, out_dir: Path | str = OUT_DIR,
                 dry_run: bool = False) -> dict:
    if isinstance(csv_paths, (str, Path)):
        csv_paths = [csv_paths]
    recs, pii = read_records(csv_paths, crs)
    index = RestaurantIndex(conn)
    by_license = {r[0]: r[1] for r in conn.execute(
        "SELECT license_id, id FROM restaurants WHERE license_id IS NOT NULL")}
    info = {r[0]: {"status": r[1], "sigungu_code": r[2]}
            for r in conn.execute("SELECT id, status, sigungu_code FROM restaurants")}

    stats = {"total": len(recs), "excluded": 0, "matched": 0, "updated": 0, "new": 0, "closed_applied": 0,
             "reopened": 0, "ignored_closed": 0, "duplicate": 0, "unmatched": 0}
    groups: dict[str, list[dict]] = {}
    new_groups: dict[tuple, list[dict]] = {}
    unmatched: list[tuple[dict, str]] = []
    for r in recs:
        if is_excluded(r["biz_type"]):
            stats["excluded"] += 1
            continue
        rid = by_license.get(r["license_id"])
        if rid is None:
            rest, reason = index.match(r["name"], r["address_road"] or r["address_jibun"], r["lat"], r["lng"])
            rid = rest.id if rest else None
        if rid is not None:
            groups.setdefault(rid, []).append(r)
            stats["matched"] += 1
            continue
        if r["status"] != "open":
            stats["ignored_closed"] += 1
        elif reason == "ambiguous":
            unmatched.append((r, "ambiguous"))
        elif r["lat"] is None:
            unmatched.append((r, f"좌표 없음·{reason}"))
        else:
            road = normalize_road_address(r["address_road"])
            key = (normalize_name(r["name"]), road or (round(r["lat"], 4), round(r["lng"], 4)))
            new_groups.setdefault(key, []).append(r)

    regions: set = set()
    for rid, rs in groups.items():
        best = max(rs, key=_priority)
        cur = info[rid]
        closed = best["status"] == "closed"
        if closed and cur["status"] == "open":
            stats["closed_applied"] += 1
        if not closed and cur["status"] == "closed":
            stats["reopened"] += 1
        # 다른 가게가 같은 관리번호를 갖고 있으면 해제(UNIQUE 충돌 방지 — 재매칭 결과 우선)
        conn.execute("UPDATE restaurants SET license_id=NULL WHERE license_id=? AND id<>?", (best["license_id"], rid))
        conn.execute(
            "UPDATE restaurants SET license_id=?, opened_at=?, license_type=?, status=?, closed_at=?, area_m2=?,"
            " phone=CASE WHEN phone IS NULL OR TRIM(phone)='' THEN ? ELSE phone END,"
            " alcohol=CASE WHEN ?=1 THEN 0 ELSE alcohol END, updated_at=? WHERE id=?",
            (best["license_id"], best["opened_at"], best["license_type"], best["status"],
             (best["closed_at"] or best["data_updated"] or best["updated_at"]) if closed else None,
             best["area_m2"], best["phone"], 1 if best["license_type"] == REST_TYPE else 0, best["updated_at"], rid),
        )
        stats["updated"] += 1
        regions.add(cur["sigungu_code"])

    region_codes = _region_map(conn)
    new_rows = []
    for rs in new_groups.values():
        best = max(rs, key=_priority)
        stats["duplicate"] += len(rs) - 1
        addr = best["address_road"] or best["address_jibun"]
        sido, gu, code = _sigungu_code(region_codes, addr)
        genre = map_genre(best["biz_type"], best["name"])
        alcohol = 0 if best["license_type"] == REST_TYPE else (1 if genre == "주점" else None)
        new_rows.append((
            f"L{best['license_id']}", best["name"], genre, best["biz_type"], alcohol, best["lat"], best["lng"], addr,
            best["address_jibun"], sido, gu, code, best["phone"], "open", best["opened_at"], best["license_type"],
            best["area_m2"], best["license_id"], best["source"], best["updated_at"],
        ))
        regions.add(code)
    cols = ("id", "name", "genre", "genre_detail", "alcohol", "lat", "lng", "address", "address_jibun", "sido",
            "sigungu", "sigungu_code", "phone", "status", "opened_at", "license_type", "area_m2", "license_id",
            "source", "updated_at")
    for row in new_rows:
        conn.execute("UPDATE restaurants SET license_id=NULL WHERE license_id=? AND id<>?", (row[-3], row[0]))
    conn.executemany(
        f"INSERT INTO restaurants({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
        f" ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols[1:])}",
        new_rows,
    )
    stats["new"] = len(new_rows)
    stats["unmatched"] = len(unmatched)

    if dry_run:
        conn.rollback()
    else:
        conn.commit()
        for reg in regions:
            rebuild_scores(conn, reg)
    path = _write_unmatched(Path(out_dir), unmatched) if unmatched else None
    return {**stats, "regions": regions, "unmatched_file": path, "pii_dropped": pii, "dry_run": dry_run}


def main() -> None:
    ap = argparse.ArgumentParser(description="인허가(일반·휴게음식점) CSV 적재(가게 매칭)")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--crs", default=DEFAULT_CRS, help=f"원본 좌표계 (기본 {DEFAULT_CRS}, 후보 {', '.join(CANDIDATE_CRS)})")
    ap.add_argument("--calibrate", action="store_true", help="후보 CRS 별 매칭 표본 거리 중앙값만 보고(적재 안 함)")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 통계만")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    conn = connect(args.db or db_path())
    init_schema(conn)
    if args.calibrate:
        recs, _ = read_records(args.csv, args.crs)
        res = calibrate(conn, recs)
        print(f"[info] 표본 {res['n']}건 (상호+도로명주소 단일 매칭)")
        for crs, m in sorted(res["medians"].items(), key=lambda kv: kv[1]):
            print(f"       {crs}: 거리 중앙값 {m} m")
        if res["best"]:
            print(f"[ok]   권장 --crs {res['best']}")
        else:
            print("[warn] 표본 없음 — 상가정보 적재 후 다시 실행")
        conn.close()
        return
    res = load_license(conn, args.csv, args.crs, args.out_dir, args.dry_run)
    tag = "[dry]" if res["dry_run"] else "[ok] "
    print(f"{tag} 전체 {res['total']}건: 매칭 {res['matched']}건(가게 {res['updated']}곳 갱신), 신규 {res['new']}곳,"
          f" 폐업 반영 {res['closed_applied']}곳, 재개업 {res['reopened']}곳, 업태 제외 {res['excluded']}건,"
          f" 미매칭 폐업 무시 {res['ignored_closed']}건, 중복 {res['duplicate']}건, 미매칭 {res['unmatched']}건")
    if not res["dry_run"]:
        print(f"[ok]   재계산 시군구 {len(res['regions'])}곳")
    for h in res["pii_dropped"]:
        print(f"[info] 개인정보 컬럼 폐기(미적재): {h}")
    if res["unmatched_file"]:
        print(f"[warn] 미매칭 {res['unmatched']}건 — 수기 검토 → {res['unmatched_file']}")
    conn.close()


if __name__ == "__main__":
    main()
