"""공공 선정·지정 목록 CSV → 가게 매칭 → restaurant_signals 적재 → 해당 시군구 점수 재계산.

    python -m app.ingest.load_designations <csv...> [--kind KIND] [--source "출처명"] [--base-date YYYY-MM-DD]
        [--check] [--dry-run] [--db PATH] [--out-dir DIR] [--allow-michelin]

입력 두 가지(자동 판별, 헤더 별칭 해석 — app.ingest.signal_common):
- 기존 고정 컬럼 CSV: name,address,lat,lng,kind,base_date,source (lat/lng 선택).
- 원본 공공 파일(모범음식점·안심식당·착한가격업소·백년가게 등): 상호(업소명/상호명/사업장명/업체명/가게명),
  주소(도로명주소/소재지도로명주소/소재지/주소/지번주소/소재지지번주소), 좌표(위도/경도, 없으면 주소 매칭),
  날짜(지정일자/지정일/선정일/인증일/기준일자/데이터기준일자), 인허가번호(관리번호 등, 있으면 우선 매칭).
  kind 열이 없으면 --kind 로 파일 전체 지정(--kind 가 있으면 kind 열보다 우선). kind = LIST_KINDS 만.
- 착한가격업소(good_price): 대표메뉴·가격(번호 붙은 대표메뉴1·가격1… 포함)이 있으면 menus 에
  source='good_price', is_signature=1 로 upsert(가게당 메뉴명 중복 없음).
- CP949/UTF-8 자동. xlsx 미지원(CSV 로 저장 안내).

매칭 실패 행은 수기 검토용 data/out/unmatched_<source>.csv(화이트리스트 컬럼 + reason, PII·전화 없음).
미슐랭(michelin_*) 은 법무 확인 전이라 기본 보류 → --allow-michelin 일 때만 적재.
중복 신호는 UNIQUE(restaurant_id,kind,value,base_date) + INSERT OR IGNORE 로 무시(재적재 멱등).
--check: 파일 점검만(DB 불필요). --dry-run: SAVEPOINT 롤백(통계·미매칭 파일만, 재계산 없음).
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from app.db import connect, db_path, init_schema
from app.scoring import prior

from . import signal_common as sc
from .signal_common import OUT_DIR

# 목록형으로 들어오는 kind (위생등급·행정처분은 load_food_safety)
LIST_KINDS = (*prior.DESIGNATION_KINDS, prior.CENTURY_KIND, prior.GOOD_PRICE_KIND, *prior.GUIDE_SCORES)
UNMATCHED_COLUMNS = sc.UNMATCHED_COLUMNS
MICHELIN_HOLD_REASON = "미슐랭: 법무 확인 전 적재 보류"
GOOD_PRICE_SOURCE = "good_price"  # menus.source

KIND_LABELS = {**prior.DESIGNATION_LABELS, prior.CENTURY_KIND: prior.CENTURY_LABEL,
               prior.GOOD_PRICE_KIND: "착한가격업소", **prior.GUIDE_LABELS}
# kind 열 값이 한글 명칭이어도 허용(공백 무시)
_KIND_BY_LABEL = {re.sub(r"\s+", "", v): k for k, v in KIND_LABELS.items()}
_KIND_BY_LABEL.update({"착한가격": prior.GOOD_PRICE_KIND, "서울미식100선": "taste_of_seoul",
                       "원산지표시우수음식점": "origin_label_excellent", "원산지우수": "origin_label_excellent"})

ALIASES = {
    **sc.COMMON_ALIASES,
    "kind": ("kind", "지정종류", "지정구분명", "지정구분"),
    "base_date": ("base_date", "지정일자", "지정일", "선정일자", "선정일", "인증일자", "인증일", "선정연도",
                  "기준일자", "데이터기준일자", "데이터기준일"),
    "menu": ("menu", "대표메뉴", "대표메뉴명", "메뉴", "메뉴명", "대표품목", "품목명", "품목"),
    "price": ("price", "가격", "가격원", "대표메뉴가격", "메뉴가격", "판매가격", "대표가격", "금액"),
}
NUMBERED = {
    "menu": re.compile(r"(?:대표메뉴|메뉴|품목)명?(\d+)(?:명)?"),
    "price": re.compile(r"(?:(?:대표메뉴|메뉴|품목)명?(\d+)(?:가격|금액)|(?:가격|금액|판매가격)(\d+))원?"),
}


def resolve_kind(raw: str | None, default: str | None) -> str:
    if default:
        return default
    v = (raw or "").strip()
    if v in LIST_KINDS:
        return v
    return _KIND_BY_LABEL.get(re.sub(r"\s+", "", v), v)


def parse_price(s: str | None) -> int | None:
    m = re.search(r"\d[\d,]*", s or "")
    if not m:
        return None
    try:
        v = int(m.group().replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v < 10_000_000 else None


def _menus_of(rec: dict) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    if rec.get("menu"):
        out.append((rec["menu"], parse_price(rec.get("price"))))
    nums: dict[str, dict] = {}
    for k, v in rec.items():
        if "#" in k:
            f, n = k.split("#", 1)
            nums.setdefault(n, {})[f] = v
    for n in sorted(nums, key=lambda x: int(x) if x.isdigit() else 0):
        d = nums[n]
        if d.get("menu"):
            out.append((d["menu"], parse_price(d.get("price"))))
    seen, uniq = set(), []
    for name, price in out:
        key = re.sub(r"\s+", "", name).lower()
        if key and key not in seen:
            seen.add(key)
            uniq.append((name.strip(), price))
    return uniq


def _table(path) -> sc.Table:
    t = sc.Table(path, ALIASES)
    t.numbered = NUMBERED
    return t


def _validate_date(s: str | None) -> str | None:
    if s is None:
        return None
    d = prior.parse_date(s)
    if d is None:
        raise ValueError(f"--base-date 형식 오류: {s} (YYYY-MM-DD)")
    return d.isoformat()


def load_designations(
    conn: sqlite3.Connection,
    csv_path,
    out_dir: Path | str = OUT_DIR,
    allow_michelin: bool = False,
    *,
    kind: str | None = None,
    source: str | None = None,
    base_date: str | None = None,
    dry_run: bool = False,
    today: date | None = None,
) -> dict:
    """반환: matched, inserted, duplicate, unmatched(보류 포함), unmatched_reasons, michelin_held, by_method,
    menus, unmatched_files, regions, dry_run."""
    if kind is not None and kind not in LIST_KINDS:
        raise ValueError(f"--kind 는 {', '.join(LIST_KINDS)} 중 하나")
    base_date = _validate_date(base_date)
    paths = [csv_path] if isinstance(csv_path, (str, Path)) else list(csv_path)
    matcher = sc.SignalMatcher(conn)
    stats = sc.new_stats()
    rows, menus, regions = [], [], set()
    unmatched: dict[str, list[dict]] = {}
    pii: list[str] = []
    updated = date.today().isoformat()
    for p in paths:
        t = _table(p)
        it = t.rows()
        first = next(it, None)
        if "name" not in t.colmap:
            raise ValueError(f"{p}: 상호 컬럼 없음 — --check 로 헤더 확인 후 signal_common.NAME_ALIASES 에 추가")
        if kind is None and "kind" not in t.colmap:
            raise ValueError(f"{p}: kind 열 없음 → --kind {{{','.join(LIST_KINDS)}}} 지정 필요")
        pii.extend(f"{Path(p).name}:{h}" for h in t.pii_dropped)
        for rec in sc.chain(first, it):
            stats["total"] += 1
            k = resolve_kind(rec.get("kind"), kind)
            src = rec.get("source") or source or KIND_LABELS.get(k) or None
            raw_date = rec.get("base_date") or None
            d = sc.iso_date(raw_date) or raw_date or base_date  # 해석 불가 원문은 보존, 빈 값만 기본값
            lat, lng = sc.coords(rec)
            addr = sc.pick_address(rec)

            def miss(reason: str):
                stats["unmatched"] += 1
                if reason == MICHELIN_HOLD_REASON:
                    stats["michelin_held"] += 1
                else:
                    stats["unmatched_reasons"][reason] += 1
                unmatched.setdefault(sc.safe_name(src), []).append(
                    sc.unmatched_item(rec, reason, kind=k, base_date=d or "", source=src or ""))

            if k not in LIST_KINDS:
                miss(f"알 수 없는 kind: {k}")
                continue
            if k in prior.MICHELIN_KINDS and not allow_michelin:
                miss(MICHELIN_HOLD_REASON)
                continue
            if not rec.get("license_id") and (not rec.get("name") or not (addr or lat is not None)):
                miss(sc.REASON_MISSING)
                continue
            rid, method, reason = matcher.match(rec.get("name", ""), addr, lat, lng, rec.get("license_id"))
            if rid is None:
                miss(reason)
                continue
            stats["matched"] += 1
            stats["by_method"][method] += 1
            rows.append((rid, k, "지정", f"{rec.get('name', '')} | {addr or ''} ({reason})", d, src))
            regions.add(matcher.region.get(rid))
            if k == prior.GOOD_PRICE_KIND:
                menus.extend((rid, m, price, GOOD_PRICE_SOURCE, updated) for m, price in _menus_of(rec))
    inserted, n_menu = sc.apply_signals(conn, rows, menus, dry_run, "load_designations")
    stats.update(inserted=inserted, duplicate=len(rows) - inserted, menus=n_menu)
    if not dry_run:
        sc.rebuild_regions(conn, regions, today)
    out = Path(out_dir)
    files = [sc.write_unmatched(out / f"unmatched_{src}.csv", items) for src, items in unmatched.items()]
    return {**stats, "unmatched_files": files, "regions": regions, "pii_dropped": pii, "dry_run": dry_run}


def check_files(paths, kind: str | None = None) -> list[dict]:
    out = []
    for p in paths:
        try:
            t = _table(p)
        except (ValueError, FileNotFoundError) as e:
            out.append({"path": str(p), "error": str(e)})
            continue
        kinds: Counter = Counter()
        no_date = [0]
        menu_rows = [0]

        def extra(rec, info):
            kinds[resolve_kind(rec.get("kind"), kind) or "(없음)"] += 1
            no_date[0] += not rec.get("base_date")
            menu_rows[0] += bool(_menus_of(rec))

        info = sc.check_table(t, extra)
        bad = {k: v for k, v in kinds.items() if k not in LIST_KINDS}
        info["dists"] = {"kind 분포": kinds, "날짜 없는 행": f"{no_date[0]:,}건(--base-date 로 기본값 지정 가능)",
                         "대표메뉴 있는 행(good_price 메뉴 적재 대상)": f"{menu_rows[0]:,}건"}
        if "kind" not in t.colmap and not kind:
            info["dists"]["[err] kind"] = "kind 열 없음 → --kind 지정 필요"
        if bad and (kind or "kind" in t.colmap):
            info["dists"]["[warn] 허용되지 않는 kind"] = ", ".join(bad)
        out.append(info)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="공공 선정·지정 목록 적재(가게 매칭)")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--kind", choices=LIST_KINDS, default=None, help="파일 전체 kind(파일에 kind 열이 없을 때)")
    ap.add_argument("--source", default=None, help='출처명(파일에 source 열이 없을 때), 예: "행정안전부 착한가격업소"')
    ap.add_argument("--base-date", default=None, help="날짜 열이 비었을 때 쓸 기준일 YYYY-MM-DD")
    ap.add_argument("--check", action="store_true", help="파일 점검만(DB 불필요)")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 통계·미매칭 파일만")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--allow-michelin", action="store_true", help="법무 확인 완료 시에만")
    args = ap.parse_args()
    if args.base_date:
        try:
            _validate_date(args.base_date)
        except ValueError as e:
            ap.error(str(e))
    if args.check:
        for info in check_files(args.csv, args.kind):
            sc.print_check(info, "app/ingest/signal_common.py·load_designations.py")
        return
    conn = connect(args.db or db_path())
    init_schema(conn)
    try:
        res = load_designations(conn, args.csv, args.out_dir, args.allow_michelin, kind=args.kind,
                                source=args.source, base_date=args.base_date, dry_run=args.dry_run)
    except (ValueError, FileNotFoundError) as e:
        conn.close()
        print(f"[err]  {e}")
        raise SystemExit(2)
    sc.print_stats(res, "지정·선정 목록")
    if res["michelin_held"]:
        print(f"[info] 미슐랭 {res['michelin_held']}건 적재 보류(법무 확인 전)")
    conn.close()


if __name__ == "__main__":
    main()
