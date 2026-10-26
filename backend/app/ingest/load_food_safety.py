"""음식점 위생등급 · 행정처분 CSV → 가게 매칭 → restaurant_signals 적재 → 해당 시군구 점수 재계산.

    python -m app.ingest.load_food_safety <csv...> --type hygiene|sanction [--source "출처명"]
        [--check] [--dry-run] [--db PATH] [--out-dir DIR]

- hygiene(식약처 음식점 위생등급 지정 현황): 업소명/상호, 소재지/주소, 위생등급/등급/지정등급, 지정일자/지정일.
  등급은 매우우수|우수|좋음 으로 정규화(★★★·★3·별3개·3단계·'매우 우수(★★★)'·AAA 등 흡수, 못 읽으면 미매칭 '등급 불명').
  지정취소 여부·지정취소일자·지정상태 열이 있으면 취소·해제·만료 행은 제외.
  → kind='hygiene_grade', value=등급, base_date=지정일자. 같은 가게 여러 행이면 점수는 최신 지정일 등급(service).
- sanction(식품접객업 행정처분): 업소명, 소재지, 처분일자/처분확정일자, 처분내용/처분명/위반내용(→ detail).
  → kind='sanction', value=처분내용 요약(같은 날 다른 처분 구분용), base_date=처분일자. 처분일자 없는 행은 미매칭.
  prior 가 기준일 최근 3년(정확히 3년 전 당일 포함) 건당 0.05, 상한 0.15 감점.
- 인허가번호(인허가번호/관리번호/허가번호/영업신고번호) 열이 있으면 restaurants.license_id 정확 일치 우선,
  없거나 불일치면 상호 + 주소(50m) 매칭. 방법별 건수 출력.
- 매칭·통계·미매칭 파일(data/out/unmatched_food_safety_<type>.csv, PII·전화 없음)·--check·--dry-run 은
  load_designations 와 같은 공통 헬퍼(app.ingest.signal_common).
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

TYPES = ("hygiene", "sanction")
KIND = {"hygiene": "hygiene_grade", "sanction": "sanction"}
DEFAULT_SOURCE = {"hygiene": "식품의약품안전처 음식점 위생등급", "sanction": "식품접객업 행정처분"}
LABEL = {"hygiene": "위생등급", "sanction": "행정처분"}

DATE_ALIASES = {
    "hygiene": ("base_date", "지정일자", "지정일", "등급지정일자", "등급지정일", "인증일자", "기준일자", "데이터기준일자"),
    "sanction": ("base_date", "처분일자", "처분확정일자", "처분일", "행정처분일자", "처분시작일자", "처분기간시작일"),
}
ALIASES = {
    "hygiene": {
        **sc.COMMON_ALIASES,
        "grade": ("grade", "value", "위생등급", "등급", "지정등급", "위생등급명", "등급명", "지정등급명"),
        "base_date": DATE_ALIASES["hygiene"],
        "cancel_flag": ("지정취소여부", "취소여부", "지정취소", "지정취소유무", "지정상태", "지정상태명", "취소구분"),
        "cancel_date": ("지정취소일자", "취소일자", "지정취소일", "지정해제일자"),
    },
    "sanction": {
        **sc.COMMON_ALIASES,
        "base_date": DATE_ALIASES["sanction"],
        "action": ("value", "처분내용", "처분명", "처분사항", "행정처분내용", "처분유형", "처분구분"),
        "violation": ("detail", "위반내용", "위반사항", "위반내역", "법령위반내용", "위반법령"),
    },
}

GRADES = ("매우우수", "우수", "좋음")
_GRADE_BY_LEVEL = {3: "매우우수", 2: "우수", 1: "좋음"}
_CANCEL_YES = {"Y", "YES", "예", "O", "1", "TRUE", "T"}
_CANCEL_WORDS = ("취소", "해제", "만료", "반납", "철회")


def normalize_grade(raw: str | None) -> str | None:
    """위생등급 표기 → 매우우수|우수|좋음 | None. 글자 등급 우선, 다음 별 개수·숫자 단계(3=매우우수)."""
    s = re.sub(r"\s+", "", raw or "")
    if not s:
        return None
    for g in GRADES:  # '매우우수' 가 '우수' 보다 먼저
        if g in s:
            return g
    m = re.fullmatch(r"(?:별|★|☆)?([123])(?:개|단계|stars?|성|★|☆)?", s, re.I)
    if m:  # '3', '★3', '별3개', '3단계', '3star' — 숫자 = 단계('1등급' 은 의미가 모호해 미해석)
        return _GRADE_BY_LEVEL[int(m.group(1))]
    stars = s.count("★")
    if stars:  # '★★★', '매우' 없이 별만
        return _GRADE_BY_LEVEL.get(min(stars, 3))
    if re.fullmatch(r"A{1,3}", s.upper()):
        return _GRADE_BY_LEVEL[len(s)]
    return prior.normalize_hygiene(s)


def is_cancelled(rec: dict) -> bool:
    flag = (rec.get("cancel_flag") or "").strip()
    if flag and (flag.upper() in _CANCEL_YES or any(w in flag for w in _CANCEL_WORDS)):
        return True
    return bool((rec.get("cancel_date") or "").strip())


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _signal_of(typ: str, rec: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """반환 (value, detail_head, base_date, 실패 사유|None)."""
    d = sc.iso_date(rec.get("base_date"))
    if typ == "hygiene":
        g = normalize_grade(rec.get("grade"))
        if g is None:
            return None, None, d, f"등급 불명: {_short(rec.get('grade') or '(빈 값)', 20)}"
        return g, None, d, None
    if d is None:
        return None, None, None, "처분일자 없음"
    action = _short(rec.get("action") or "", 60)
    detail = " / ".join(x for x in (_short(rec.get("action") or "", 200), _short(rec.get("violation") or "", 300)) if x)
    return action or "행정처분", detail or None, d, None


def load_food_safety(conn: sqlite3.Connection, csv_paths, typ: str, out_dir: Path | str = OUT_DIR, *,
                     source: str | None = None, dry_run: bool = False, today: date | None = None) -> dict:
    if typ not in TYPES:
        raise ValueError(f"--type 은 {'|'.join(TYPES)}")
    paths = [csv_paths] if isinstance(csv_paths, (str, Path)) else list(csv_paths)
    kind = KIND[typ]
    matcher = sc.SignalMatcher(conn)
    stats = sc.new_stats()
    excluded: Counter = Counter()
    rows, regions, unmatched, pii = [], set(), [], []
    for p in paths:
        t = sc.Table(p, ALIASES[typ])
        it = t.rows()
        first = next(it, None)
        if "name" not in t.colmap:
            raise ValueError(f"{p}: 상호 컬럼 없음 — --check 로 헤더 확인 후 signal_common.NAME_ALIASES 에 추가")
        need = "grade" if typ == "hygiene" else "base_date"
        if need not in t.colmap:
            raise ValueError(f"{p}: {'위생등급' if typ == 'hygiene' else '처분일자'} 컬럼 없음 — --check 로 헤더 확인"
                             f" 후 load_food_safety.ALIASES 에 추가")
        pii.extend(f"{Path(p).name}:{h}" for h in t.pii_dropped)
        for rec in sc.chain(first, it):
            stats["total"] += 1
            src = rec.get("source") or source or DEFAULT_SOURCE[typ]
            value, detail, d, bad = _signal_of(typ, rec)

            def miss(reason: str):
                stats["unmatched"] += 1
                stats["unmatched_reasons"][reason.split(":")[0]] += 1
                unmatched.append(sc.unmatched_item(rec, reason, kind=kind, value=value or rec.get("grade") or "",
                                                   detail=detail or "", base_date=d or rec.get("base_date") or "",
                                                   source=src))

            if typ == "hygiene" and is_cancelled(rec):
                stats["excluded"] += 1
                excluded["지정취소·해제 행"] += 1
                continue
            if bad:
                miss(bad)
                continue
            lat, lng = sc.coords(rec)
            addr = sc.pick_address(rec)
            if not rec.get("license_id") and (not rec.get("name") or not (addr or lat is not None)):
                miss(sc.REASON_MISSING)
                continue
            rid, method, reason = matcher.match(rec.get("name", ""), addr, lat, lng, rec.get("license_id"))
            if rid is None:
                miss(reason)
                continue
            stats["matched"] += 1
            stats["by_method"][method] += 1
            head = f"{rec.get('name', '')} | {addr or ''} ({reason})"
            rows.append((rid, kind, value, f"{detail} — {head}" if detail else head, d, src))
            regions.add(matcher.region.get(rid))
    inserted, _ = sc.apply_signals(conn, rows, None, dry_run, "load_food_safety")
    stats.update(inserted=inserted, duplicate=len(rows) - inserted)
    if not dry_run:
        sc.rebuild_regions(conn, regions, today)
    path = Path(out_dir) / f"unmatched_food_safety_{typ}.csv"
    if unmatched:
        files = [sc.write_unmatched(path, unmatched)]
    else:
        files = []
        path.unlink(missing_ok=True)  # 지난 실행의 오래된 미매칭 목록 제거
    return {**stats, "excluded_reasons": dict(excluded), "unmatched_files": files, "regions": regions,
            "pii_dropped": pii, "dry_run": dry_run}


def check_files(paths, typ: str) -> list[dict]:
    out = []
    for p in paths:
        try:
            t = sc.Table(p, ALIASES[typ])
        except (ValueError, FileNotFoundError) as e:
            out.append({"path": str(p), "error": str(e)})
            continue
        dist: Counter = Counter()
        bad: Counter = Counter()
        dates: list[str] = []
        cancelled = [0]

        def extra(rec, info):
            value, _detail, d, why = _signal_of(typ, rec)
            if typ == "hygiene":
                if is_cancelled(rec):
                    cancelled[0] += 1
                    return
                if value:
                    dist[value] += 1
                else:
                    bad[_short(rec.get("grade") or "(빈 값)", 20)] += 1
            else:
                dist[value or "(처분일자 없음)"] += 1
            if d:
                dates.append(d)

        info = sc.check_table(t, extra)
        info["dists"] = {}
        need = "grade" if typ == "hygiene" else "base_date"
        if need not in t.colmap:
            info["missing_fields"].append(need)
        if typ == "hygiene":
            info["dists"]["등급 분포(정규화)"] = dist
            if bad:
                info["dists"]["[warn] 해석 못 한 등급 표기(미매칭 처리)"] = bad
            info["dists"]["지정취소·해제 제외"] = f"{cancelled[0]:,}건"
        else:
            info["dists"]["처분내용 상위"] = dist
            if dates:
                three = prior._years_ago(date.today(), prior.SANCTION_YEARS).isoformat()
                recent = sum(1 for x in dates if x >= three)
                info["dists"]["처분일자 범위"] = f"{min(dates)} ~ {max(dates)}, 최근 3년({three}~) {recent:,}건"
        if not dates:
            info["dists"]["[warn] 날짜"] = "날짜 열 없음/해석 불가"
        out.append(info)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="위생등급·행정처분 CSV 적재(가게 매칭)")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--type", required=True, choices=TYPES, dest="typ")
    ap.add_argument("--source", default=None, help="출처명(파일에 source 열이 없을 때)")
    ap.add_argument("--check", action="store_true", help="파일 점검만(DB 불필요)")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 통계·미매칭 파일만")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    if args.check:
        for info in check_files(args.csv, args.typ):
            sc.print_check(info, "app/ingest/signal_common.py·load_food_safety.py")
        return
    conn = connect(args.db or db_path())
    init_schema(conn)
    try:
        res = load_food_safety(conn, args.csv, args.typ, args.out_dir, source=args.source, dry_run=args.dry_run)
    except (ValueError, FileNotFoundError) as e:
        conn.close()
        print(f"[err]  {e}")
        raise SystemExit(2)
    sc.print_stats(res, LABEL[args.typ])
    conn.close()


if __name__ == "__main__":
    main()
