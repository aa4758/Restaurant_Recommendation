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
from collections.abc import Iterable, Iterator
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
CALIBRATE_MIN_N = 30  # 이보다 적으면 calibrate 결과 경고


def iter_records(paths, crs: str = DEFAULT_CRS, pii: list[str] | None = None) -> Iterator[dict]:
    """파일들을 행 단위로 스트리밍. pii 목록이 주어지면 파일별 폐기 PII 헤더를 채움."""
    for p in paths:
        ad = LicenseCSVAdapter(p, crs)
        yield from ad.iter_records()
        if pii is not None:
            pii.extend(f"{Path(p).name}:{h}" for h in ad.pii_dropped)


def read_records(paths, crs: str = DEFAULT_CRS) -> tuple[list[dict], list[str]]:
    pii: list[str] = []
    recs = list(iter_records(paths, crs, pii))
    return recs, pii


# --- calibrate ---------------------------------------------------------------
def calibrate(conn: sqlite3.Connection, recs: Iterable[dict], candidates=CANDIDATE_CRS,
              sample: int = CALIBRATE_SAMPLE) -> dict:
    """반환: {"n": 표본 수, "medians": {crs: 중앙값 m}, "best": crs | None, "warning": str | None}.

    모든 후보 CRS 로 변환이 성공한 쌍만 표본(같은 표본으로 비교). n < CALIBRATE_MIN_N 이면 warning.
    """
    index = RestaurantIndex(conn)
    pairs = []  # [(rest, {crs: (lat, lng)})]
    for r in recs:
        if not (r["x"] and r["y"] and r["address_road"]) or is_excluded(r["biz_type"]):
            continue
        hits = [c for c in index.name_candidates(r["name"]) if addresses_match(r["address_road"], c.address)]
        if len(hits) != 1:
            continue
        lls = {crs: tm_to_wgs84(r["x"], r["y"], crs) for crs in candidates}
        if any(v is None for v in lls.values()):
            continue
        pairs.append((hits[0], lls))
        if len(pairs) >= sample:
            break
    medians = {}
    if pairs:
        for crs in candidates:
            medians[crs] = round(statistics.median(
                haversine_m(lls[crs][0], lls[crs][1], rest.lat, rest.lng) for rest, lls in pairs), 1)
    best = min(medians, key=medians.get) if medians else None
    warning = None
    if 0 < len(pairs) < CALIBRATE_MIN_N:
        warning = f"표본 {len(pairs)}건 < {CALIBRATE_MIN_N} — 결과 신뢰도 낮음"
    return {"n": len(pairs), "medians": medians, "best": best, "warning": warning}


# --- 적재 ----------------------------------------------------------------------
def _priority(r: dict) -> tuple:
    """같은 가게 다중 인허가 중 반영할 1건: 영업 중 > (영업 중이면) 일반 > 휴게 > 최신 인허가일자 > 최신 갱신일 > 관리번호.

    영업 중 일반·휴게가 공존하면 일반이 이김 → best 가 영업 중 휴게면 영업 중 인허가는 모두 휴게.
    """
    is_open = r["status"] == "open"
    return (is_open, is_open and r["license_type"] != REST_TYPE, r["opened_at"] or "", r["data_updated"] or "",
            r["license_id"])


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
        if short:
            code = regions.get((short, key)) or regions.get(("", key))
        else:
            # 시도 없는 주소: 같은 시군구명이 여러 시도에 있으면(예: 중구) 특정 불가 → None
            codes = {c for (s, g), c in regions.items() if g == key}
            if len(codes) > 1:
                return sido, gu, None
            code = next(iter(codes), None)
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


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """alcohol_src: 'license' = 휴게음식점 인허가로 alcohol=0 을 강제한 값(휴게→일반 전환 시 NULL 로 복원 판별용)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(restaurants)")}
    if "alcohol_src" not in cols:
        conn.execute("ALTER TABLE restaurants ADD COLUMN alcohol_src TEXT")


def _keep_best(d: dict, key, r: dict) -> None:
    """그룹별 best 행과 행 수만 유지(전국 규모 메모리 상수화)."""
    cur = d.get(key)
    if cur is None:
        d[key] = [r, 1]
    else:
        cur[1] += 1
        if _priority(r) > _priority(cur[0]):
            cur[0] = r


def load_license(conn: sqlite3.Connection, csv_paths, crs: str = DEFAULT_CRS, out_dir: Path | str = OUT_DIR,
                 dry_run: bool = False) -> dict:
    if isinstance(csv_paths, (str, Path)):
        csv_paths = [csv_paths]
    pii: list[str] = []
    index = RestaurantIndex(conn)
    by_license = {r[0]: r[1] for r in conn.execute(
        "SELECT license_id, id FROM restaurants WHERE license_id IS NOT NULL")}
    info = {r[0]: {"status": r[1], "sigungu_code": r[2], "license_id": r[3], "opened_at": r[4]}
            for r in conn.execute("SELECT id, status, sigungu_code, license_id, opened_at FROM restaurants")}

    stats = {"total": 0, "excluded": 0, "matched": 0, "updated": 0, "new": 0, "closed_applied": 0,
             "reopened": 0, "ignored_closed": 0, "stale_ignored": 0, "duplicate": 0, "unmatched": 0}
    groups: dict[str, list] = {}       # 가게 id → [best 행, 행 수]
    new_groups: dict[tuple, list] = {}  # (상호, 도로명키|좌표) → [best 행, 행 수]
    unmatched: list[tuple[dict, str]] = []
    for r in iter_records(csv_paths, crs, pii):
        stats["total"] += 1
        excluded = is_excluded(r["biz_type"])
        if excluded:
            stats["excluded"] += 1
            r["_excluded"] = True  # 기존 가게 상태·폐업 반영에만 사용, 신규 생성·미매칭 보고 안 함
        rid = by_license.get(r["license_id"])
        reason = "관리번호 일치"
        if rid is None:
            rest, reason = index.match(r["name"], r["address_road"] or r["address_jibun"], r["lat"], r["lng"])
            rid = rest.id if rest else None
        if rid is not None:
            _keep_best(groups, rid, r)
            stats["matched"] += 1
            continue
        if excluded:
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
            _keep_best(new_groups, key, r)

    conn.execute("SAVEPOINT load_license")
    try:
        _ensure_columns(conn)
        regions = _apply(conn, groups, new_groups, info, stats)
    except BaseException:
        conn.execute("ROLLBACK TO load_license")
        conn.execute("RELEASE load_license")
        raise
    stats["unmatched"] = len(unmatched)

    if dry_run:
        conn.execute("ROLLBACK TO load_license")  # 이 함수의 변경만 되돌림(호출자 트랜잭션 보존)
        conn.execute("RELEASE load_license")
    else:
        conn.execute("RELEASE load_license")
        conn.commit()
        for reg in regions:
            rebuild_scores(conn, reg)
    out = Path(out_dir)
    if unmatched:
        path = _write_unmatched(out, unmatched)
    else:
        path = None
        (out / UNMATCHED_FILE).unlink(missing_ok=True)  # 지난 실행의 오래된 미매칭 목록 제거
    return {**stats, "regions": regions, "unmatched_file": path, "pii_dropped": pii, "dry_run": dry_run}


def _apply(conn: sqlite3.Connection, groups: dict, new_groups: dict, info: dict, stats: dict) -> set:
    regions: set = set()
    for rid, (best, _n) in groups.items():
        cur = info[rid]
        closed = best["status"] == "closed"
        if (closed and cur["status"] == "open" and cur["license_id"] and best["license_id"] != cur["license_id"]
                and cur["opened_at"] and not (best["opened_at"] and best["opened_at"] >= cur["opened_at"])):
            # 이미 영업 중 인허가가 붙은 가게에, 그보다 오래된 다른 관리번호의 폐업 행(이전 실행·다른 파일) → 무시
            stats["stale_ignored"] += 1
            continue
        if closed and cur["status"] == "open":
            stats["closed_applied"] += 1
        if not closed and cur["status"] == "closed":
            stats["reopened"] += 1
        closed_at = (best["closed_at"] or best["data_updated"]) if closed else None  # 적재일은 쓰지 않음(멱등)
        if best.get("_excluded"):
            # 제외 업태 행: 기존 가게의 영업 상태·폐업만 반영
            conn.execute(
                "UPDATE restaurants SET status=?, closed_at=CASE WHEN ?='closed' THEN COALESCE(closed_at, ?) END,"
                " updated_at=? WHERE id=?",
                (best["status"], best["status"], closed_at, best["updated_at"], rid),
            )
        else:
            is_open = not closed
            force_zero = 1 if is_open and best["license_type"] == REST_TYPE else 0  # 영업 중 인허가가 모두 휴게
            restore = 1 if is_open and best["license_type"] and best["license_type"] != REST_TYPE else 0
            # 다른 가게가 같은 관리번호를 갖고 있으면 해제(UNIQUE 충돌 방지 — 재매칭 결과 우선)
            conn.execute("UPDATE restaurants SET license_id=NULL WHERE license_id=? AND id<>?",
                         (best["license_id"], rid))
            conn.execute(
                "UPDATE restaurants SET license_id=?, opened_at=COALESCE(?, opened_at), license_type=?, status=?,"
                " closed_at=CASE WHEN ?='closed' THEN COALESCE(closed_at, ?) END, area_m2=COALESCE(?, area_m2),"
                " phone=CASE WHEN phone IS NULL OR TRIM(phone)='' THEN ? ELSE phone END,"
                " alcohol=CASE WHEN ?=1 THEN 0"
                "  WHEN ?=1 AND alcohol_src='license' AND alcohol=0 THEN NULL ELSE alcohol END,"
                " alcohol_src=CASE WHEN ?=1 THEN 'license' WHEN ?=1 AND alcohol_src='license' THEN NULL"
                "  ELSE alcohol_src END,"
                " updated_at=? WHERE id=?",
                (best["license_id"], best["opened_at"], best["license_type"], best["status"], best["status"],
                 closed_at, best["area_m2"], best["phone"], force_zero, restore, force_zero, restore,
                 best["updated_at"], rid),
            )
        stats["updated"] += 1
        regions.add(cur["sigungu_code"])

    region_codes = _region_map(conn)
    new_rows = []
    for best, n in new_groups.values():
        stats["duplicate"] += n - 1
        addr = best["address_road"] or best["address_jibun"]
        sido, gu, code = _sigungu_code(region_codes, addr)
        genre = map_genre(best["biz_type"], best["name"])
        rest = best["license_type"] == REST_TYPE
        alcohol = 0 if rest else (1 if genre == "주점" else None)
        new_rows.append((
            f"L{best['license_id']}", best["name"], genre, best["biz_type"], alcohol, "license" if rest else None,
            best["lat"], best["lng"], addr, best["address_jibun"], sido, gu, code, best["phone"], "open",
            best["opened_at"], best["license_type"], best["area_m2"], best["license_id"], best["source"],
            best["updated_at"],
        ))
        regions.add(code)
    cols = ("id", "name", "genre", "genre_detail", "alcohol", "alcohol_src", "lat", "lng", "address",
            "address_jibun", "sido", "sigungu", "sigungu_code", "phone", "status", "opened_at", "license_type",
            "area_m2", "license_id", "source", "updated_at")
    for row in new_rows:
        conn.execute("UPDATE restaurants SET license_id=NULL WHERE license_id=? AND id<>?", (row[-3], row[0]))
    conn.executemany(
        f"INSERT INTO restaurants({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
        f" ON CONFLICT(id) DO UPDATE SET {','.join(f'{c}=excluded.{c}' for c in cols[1:])}",
        new_rows,
    )
    stats["new"] = len(new_rows)
    return regions


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
        res = calibrate(conn, iter_records(args.csv, args.crs))
        print(f"[info] 표본 {res['n']}건 (상호+도로명주소 단일 매칭, 모든 후보 CRS 변환 성공)")
        if res["warning"]:
            print(f"[warn] {res['warning']}")
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
          f" 미매칭 폐업 무시 {res['ignored_closed']}건, 오래된 폐업 무시 {res['stale_ignored']}건, 중복 {res['duplicate']}건, 미매칭 {res['unmatched']}건")
    if not res["dry_run"]:
        print(f"[ok]   재계산 시군구 {len(res['regions'])}곳")
    for h in res["pii_dropped"]:
        print(f"[info] 개인정보 컬럼 폐기(미적재): {h}")
    if res["unmatched_file"]:
        print(f"[warn] 미매칭 {res['unmatched']}건 — 수기 검토 → {res['unmatched_file']}")
    conn.close()


if __name__ == "__main__":
    main()
