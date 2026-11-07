"""공공기관 업무추진비 집행내역 → 가게 매칭 → gov_expense 적재 → 해당 시군구 점수 재계산.

    python -m app.ingest.load_gov_expense --fetch-seoul [--key KEY]       # 서울시 본청 Open API → CSV
    python -m app.ingest.load_gov_expense <csv...> [--since YYYY-MM-DD] [--check] [--dry-run] [--db PATH]

서울시 본청: 열린데이터광장 OA-22156 'odExpense'(공공누리 1유형). 인증키는 SEOUL_API_KEY 또는 --key.
받을 때부터 화이트리스트 열만 저장(작성자·전화·집행대상 성명 등 PII 는 버림) → data/raw/gov_expense/.

입력 CSV(정규화 열): exec_dt, agency, dept, place, amount, category, source.
- place 는 '상호(서울 중구 세종대로 136)' 형식 → 상호 + 도로명 주소로 기존 매칭기(상호+주소/50m) 사용.
  괄호 안이 주소가 아니면 주소 없음 → 미매칭(data/out/unmatched_<source>.csv).
  단 agency 가 '서울특별시 구로구'처럼 시군구까지 있으면 상호+시군구 유일 매칭(match_city, 전국 동명 30곳 미만)으로 대신함.
  시군구 없는 기관(중앙부처·교육청)은 청사 시군구(AGENCY_HOME·교육지원청 이름)로 같은 매칭.
- expense_collector 산출(gov_expense_for_jjinmat.csv: restaurant_name·address·exec_date…)도 그대로 읽음.
- 금액 0 이하(취소)·--since 이전(기본: 2년 전 같은 달 1일)은 제외. 같은 (일시, 장소, 금액, 부서) 중복은 1건.
- purpose 에는 집행목적 원문 대신 비목(category: 시책·기관운영 등)만 저장(목적 문구에 성명이 섞일 수 있음).
- 재적재 멱등: 같은 source 의 기존 행을 지우고 다시 넣음(source = 기관 단위 전체 교체).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

from app.db import BACKEND_DIR, connect, db_path, init_schema

from . import signal_common as sc
from .matcher import _sido
from .signal_common import OUT_DIR

RAW_DIR = BACKEND_DIR / "data" / "raw" / "gov_expense"
COLUMNS = ("exec_dt", "agency", "dept", "place", "amount", "category", "source")
SEOUL_SOURCE = "서울시 본청 업무추진비"
SEOUL_API = "http://openapi.seoul.go.kr:8088/{key}/json/odExpense/{start}/{end}/"
PAGE = 1000  # Open API 1회 최대

# 주소 시작: '(서울 …' 우선, 없으면 ', 서울 …' · ' 중구 …' (시도 생략). 괄호 중첩·안 닫힘도 이 지점에서 자름
_ADDR_TOK = (r"(?=(?:[가-힣]{2,4}(?:특별시|광역시|특별자치시|특별자치도|도)|전남광주|서울|부산|대구|인천|광주|대전|울산|세종|경기|"
             r"강원|충북|충남|전북|전남|경북|경남|제주|[가-힣]{1,4}[시군구]) )")
_ADDR_START = (re.compile(r"\s*\(\s*" + _ADDR_TOK), re.compile(r"[\s,]+" + _ADDR_TOK))
_ADDR_HINT = re.compile(r"(로|길)\s*\d")
_GLUED_BLDG = re.compile(r"(로|길)(\d+(?:-\d+)?)(?=[\s,)]|$)")  # '서소문로115' → '서소문로 115' ('을지로3길'은 그대로)

GOV_MAX_CANDS = 30  # 상호+시군 매칭의 전국 동명 상한(지정목록 8보다 완화, 2026-11-07 결정)
# 시군구가 없는 기관 → 청사 소재 (시도, 시군구). 그 시군구 안 상호 유일 매칭. 세종은 시군구 ''.
# ponytail: 수기 표 — 새 기관은 여기에 추가. 전국 단위로 쓰는 기관(해양경찰청 등)은 청사 기준이라 오매칭 위험 있음
AGENCY_HOME = {
    "전북특별자치도": ("전북", "전주시"), "전북특별자치도교육청": ("전북", "전주시"), "해양경찰청": ("인천", "연수구"),
    "부산광역시교육청": ("부산", "부산진구"), "부산광역시서부교육지원청": ("부산", "서구"), "공정거래위원회": ("세종", ""),
    "지식재산처": ("대전", "서구"), "해양수산부": ("세종", ""), "산업통상부": ("세종", ""), "개인정보보호위원회": ("서울", "종로구"),
}
_EDU_OFFICE = re.compile(r"^(\S+?(?:특별시|광역시|특별자치시|특별자치도|도))(\S+)교육지원청$")  # '경기도군포의왕교육지원청'


def agency_homes(agency: str, cities: dict[str, set[str]]) -> list[tuple[str, str]]:
    """기관명 → 청사 후보 (시도, 시군구) 목록. 교육지원청은 이름 속 시군 이름들(cities: 시도 → 시군구 첫 토큰)."""
    if agency in AGENCY_HOME:
        return [AGENCY_HOME[agency]]
    m = _EDU_OFFICE.match(agency)
    if not m:
        return []
    sd, rest, out = _sido(m.group(1)), m.group(2), []
    for c in sorted(cities.get(_sido(m.group(1)) or "", ()), key=len, reverse=True):  # 긴 이름 먼저: '남양주' 다음 '양주'
        stem = c[:-1]
        if len(stem) >= 2 and stem in rest:
            out.append((sd, c))
            rest = rest.replace(stem, "", 1)
    return out


def parse_place(place: str | None) -> tuple[str, str | None]:
    """'상호(서울 중구 세종대로 136)' → (상호, 주소). 주소(도로명+번호)가 없으면 (원문, None)."""
    s = re.sub(r"\s+", " ", place or "").strip()
    m = _ADDR_START[0].search(s) or _ADDR_START[1].search(s)
    if not m or m.start() == 0:
        return s, None
    name, addr = s[:m.start()].strip(), _GLUED_BLDG.sub(r"\1 \2", s[m.end():].rstrip(") "))
    if not name or not _ADDR_HINT.search(addr):
        return s, None
    return name, addr


def default_since(today: date | None = None) -> str:
    t = today or date.today()
    return date(t.year - 2, t.month, 1).isoformat()


def seoul_row(r: dict) -> dict:
    """odExpense 행 → 정규화 행(화이트리스트). WRITER·TELNO·TARGET_NM·EXEC_PURPOSE 는 버림."""
    return {"exec_dt": r.get("EXEC_DT") or "", "agency": "서울특별시", "dept": r.get("DEPT_NM_FULL") or r.get("DEPT_NM") or "",
            "place": r.get("EXEC_LOC") or "", "amount": r.get("EXEC_AMOUNT") or "", "category": r.get("BIMOK") or "",
            "source": SEOUL_SOURCE}


def fetch_seoul(key: str, out_dir: Path | str = RAW_DIR, opener=urllib.request.urlopen) -> tuple[Path, int]:
    """서울시 본청 전체 집행내역을 받아 정규화 CSV 로 저장. 반환 (경로, 행 수)."""
    rows, start, total = [], 1, None
    while total is None or start <= total:
        url = SEOUL_API.format(key=key, start=start, end=start + PAGE - 1)
        with opener(url, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        data = body.get("odExpense") or body
        code = (data.get("RESULT") or {}).get("CODE")
        if code != "INFO-000":
            raise RuntimeError(f"odExpense 오류 {code}: {(data.get('RESULT') or {}).get('MESSAGE')}")
        total = int(data["list_total_count"])
        rows.extend(seoul_row(r) for r in data.get("row", []))
        start += PAGE
    path = Path(out_dir) / f"seoul_odExpense_{date.today():%Y%m%d}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


def read_rows(paths, since: str) -> tuple[list[dict], dict]:
    """정규화 CSV → 기간 안·금액>0·중복 제거 행. 반환 (행, 제외 통계)."""
    out, seen = [], set()
    skipped = {"기간 밖": 0, "금액 0 이하": 0, "중복": 0}
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if "exec_dt" not in r:  # expense_collector export 형식 → 정규화 열. purpose(목적 원문)는 PII 우려로 버림
                    name, addr = (r.get("restaurant_name") or "").strip(), (r.get("address") or "").strip()
                    r = {"exec_dt": r.get("exec_date"), "agency": r.get("agency"), "place": f"{name}({addr})" if addr else name,
                         "amount": r.get("amount"), "source": r.get("source")}
                r = {k: (r.get(k) or "").strip() for k in COLUMNS}
                if r["exec_dt"][:10] < since:
                    skipped["기간 밖"] += 1
                    continue
                amount = int(float(r["amount"].replace(",", "") or 0))
                if amount <= 0:
                    skipped["금액 0 이하"] += 1
                    continue
                key = (r["exec_dt"], r["place"], amount, r["dept"])
                if key in seen:
                    skipped["중복"] += 1
                    continue
                seen.add(key)
                out.append({**r, "amount": amount})
    return out, skipped


def load_gov_expense(conn: sqlite3.Connection, csv_paths, since: str | None = None, out_dir: Path | str = OUT_DIR,
                     dry_run: bool = False, today: date | None = None) -> dict:
    since = since or default_since(today)
    recs, skipped = read_rows([csv_paths] if isinstance(csv_paths, (str, Path)) else csv_paths, since)
    matcher = sc.SignalMatcher(conn)
    stats = sc.new_stats()
    stats.update(excluded=sum(skipped.values()), excluded_reasons=skipped)
    rows, regions, sources = [], set(), set()
    unmatched: dict[str, list[dict]] = {}
    cities: dict[str, set[str]] = {}
    for sd, sg in conn.execute("SELECT DISTINCT sido, sigungu FROM restaurants WHERE sigungu IS NOT NULL"):
        cities.setdefault(_sido(sd or ""), set()).add(sg.split()[0])
    homes_cache: dict[str, list] = {}
    for r in recs:
        stats["total"] += 1
        name, addr = parse_place(r["place"])
        if not addr and " " in r["agency"]:  # '상호(낙성대로 16)' → 기관 시군구를 앞에 붙여 다시
            name, addr = parse_place(re.sub(r"\(\s*(?=[^()]*(?:로|길)\s*\d)", f"({r['agency']} ", r["place"], count=1))
        sources.add(r["source"])
        rid, method, reason = matcher.match(name, addr, None, None) if addr else (None, None, "장소에 주소 없음")
        if not addr and " " in r["agency"]:  # 구청 게시판 상호만 → 상호+시군구 유일 매칭(주소 불일치엔 안 씀: 오매칭)
            rid, method, reason = matcher.match_city(name, *r["agency"].split(" ", 1), max_cands=GOV_MAX_CANDS)
        elif not addr:  # 시군구 없는 기관 → 청사 시군구(들) 안 유일 매칭. 여러 시군에 1곳씩이면 모호 → 안 붙임
            homes = homes_cache.setdefault(r["agency"], agency_homes(r["agency"], cities))
            hits = [matcher.match_city(name, sd, city, max_cands=GOV_MAX_CANDS) for sd, city in homes]
            ids = {h[0] for h in hits if h[0]}
            if len(ids) == 1:
                rid, method, reason = ids.pop(), "name+agency_home", "기관 소재 시군구 유일"
            elif hits:
                rid, method, reason = None, None, "기관 소재: " + ("여러 시군 후보" if ids else hits[0][2])
        if rid is None:
            stats["unmatched"] += 1
            stats["unmatched_reasons"][reason] += 1
            unmatched.setdefault(sc.safe_name(r["source"]), []).append(
                {"name": name, "address": addr or "", "base_date": r["exec_dt"][:10], "source": r["source"],
                 "reason": reason})
            continue
        stats["matched"] += 1
        stats["by_method"][method] += 1
        rows.append((rid, r["exec_dt"][:10], r["agency"], r["amount"], r["category"] or None, r["source"],
                     int(r["exec_dt"][:4])))
        regions.add(matcher.region.get(rid))
    conn.execute("SAVEPOINT load_gov")
    try:
        for src in sources:  # source 단위 전체 교체(멱등)
            regions.update(matcher.region.get(x) for (x,) in conn.execute(
                "SELECT DISTINCT restaurant_id FROM gov_expense WHERE source=?", (src,)))
            conn.execute("DELETE FROM gov_expense WHERE source=?", (src,))
        conn.executemany("INSERT INTO gov_expense(restaurant_id,exec_date,agency,amount,purpose,source,base_year)"
                         " VALUES(?,?,?,?,?,?,?)", rows)
    except BaseException:
        conn.execute("ROLLBACK TO load_gov")
        conn.execute("RELEASE load_gov")
        raise
    if dry_run:
        conn.execute("ROLLBACK TO load_gov")
    conn.execute("RELEASE load_gov")
    if not dry_run:
        conn.commit()
        sc.rebuild_regions(conn, regions, today)
    stats["inserted"] = len(rows)
    files = [sc.write_unmatched(Path(out_dir) / f"unmatched_{src}.csv", items) for src, items in unmatched.items()]
    return {**stats, "since": since, "stores": len({r[0] for r in rows}),
            "unmatched_files": files, "regions": regions, "dry_run": dry_run}


def check_files(paths, since: str) -> dict:
    recs, skipped = read_rows(paths, since)
    with_addr = sum(parse_place(r["place"])[1] is not None for r in recs)
    return {"rows": len(recs), "with_address": with_addr, "skipped": skipped, "since": since,
            "sources": sorted({r["source"] for r in recs})}


def main() -> None:
    ap = argparse.ArgumentParser(description="공공기관 업무추진비 적재(가게 매칭)")
    ap.add_argument("csv", nargs="*")
    ap.add_argument("--fetch-seoul", action="store_true", help="서울시 본청 Open API 에서 받아 CSV 저장")
    ap.add_argument("--key", default=None, help="열린데이터광장 인증키(기본: SEOUL_API_KEY)")
    ap.add_argument("--since", default=None, help="이 날짜 이후 집행만(기본: 2년 전 같은 달 1일)")
    ap.add_argument("--check", action="store_true", help="파일 점검만(DB 불필요)")
    ap.add_argument("--dry-run", action="store_true", help="DB 변경 없이 통계·미매칭 파일만")
    ap.add_argument("--db", default=None, help="SQLite 경로 (기본: JJINMAT_DB 또는 data/jjinmat.db)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    if args.fetch_seoul:
        key = (args.key or os.environ.get("SEOUL_API_KEY", "")).strip()
        if not key:
            ap.error("인증키 필요: --key 또는 환경변수 SEOUL_API_KEY")
        path, n = fetch_seoul(key)
        print(f"[ok]   {n:,}행 → {path}")
        return
    if not args.csv:
        ap.error("CSV 경로 또는 --fetch-seoul 필요")
    since = args.since or default_since()
    if args.check:
        info = check_files(args.csv, since)
        print(f"[info] {info['since']} 이후 {info['rows']:,}행 · 장소에 주소 있음 {info['with_address']:,}"
              f" · 제외 {info['skipped']} · 출처 {info['sources']}")
        return
    conn = connect(args.db or db_path())
    init_schema(conn)
    res = load_gov_expense(conn, args.csv, since, args.out_dir, args.dry_run)
    sc.print_stats(res, "업무추진비")
    print(f"[info] {res['since']} 이후 집행 · 매칭 가게 {res['stores']:,}곳")
    conn.close()


if __name__ == "__main__":
    main()
