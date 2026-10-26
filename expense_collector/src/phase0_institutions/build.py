"""Phase 0 — 기관 마스터 리스트.

출처
1. 기관 목록: 행정표준코드관리시스템(code.go.kr) '기관코드 전체자료' (공공데이터포털 15092039 의 다운로드 링크)
2. 홈페이지: 정부24 '정부/지자체 누리집'(gov.kr/portal/orgSite, robots 명시 허용)
3. 교육지원청 홈페이지: 정부24 에 없음 → 시도교육청 홈페이지(JS 리다이렉트 몇 단계)의 '○○교육지원청' 바로가기 링크
홈페이지를 못 찾은 기관은 status=excluded (2026-10-27 사용자 결정: URL 미확보 기관은 제외).

원본은 data/raw/_phase0/ 에 캐시(있으면 재다운로드 안 함, 갱신하려면 파일 삭제).
"""
import csv
import io
import re
import zipfile
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from src import db
from src.http_client import HttpClient
from src.web import anchors, fetch_followed, robots_blocked

CODE_URL = "https://www.code.go.kr/etc/codeFullDown.do?codeseId=00001"
CODE_MEMBER = "기관코드 전체자료(유형분류 의미추가).txt"
GOVKR_URL = "https://www.gov.kr/portal/orgSite"

EXPECTED = {"METRO_EDU": 17, "LOCAL_EDU": 176, "METRO_GOV": 17, "LOCAL_GOV": 226, "CENTRAL": 50, "OTHER": 0}
CENTRAL_KINDS = {"부", "처", "청", "위원회", "국무총리직속(위원회)"}
LOCAL_KINDS = {"군", "도농복합시", "일반시", "자치구"}
# 정부24 목록이 통합 전 명칭으로 남아 있는 경우 — 매칭은 하되 needs_review 로 둔다
MERGED_ALIASES = {"전남광주통합특별시": ("전라남도", "광주광역시")}
CSV_COLS = ["institution_id", "name", "type", "parent", "region", "homepage_url", "admin_code", "status", "note"]


# --- 1. 기관코드 ---
def load_codes(client: HttpClient, raw: Path) -> pd.DataFrame:
    path = raw / "code_go_kr_org_00001.zip"
    if not path.exists():
        r = client.get(CODE_URL)
        r.raise_for_status()
        path.write_bytes(r.content)
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if _zipname(n) == CODE_MEMBER)
        text = z.read(member).decode("cp949")
    return pd.read_csv(io.StringIO(text), sep="\t", dtype=str, na_values=["NULL"], keep_default_na=False)


def _zipname(n: str) -> str:
    try:
        return n.encode("cp437").decode("cp949")  # zip 이 UTF-8 플래그 없이 cp949 로 저장됨
    except UnicodeError:
        return n


def select_institutions(df: pd.DataFrame) -> list[dict]:
    live = df[df["존폐여부"] == "0"]
    mid, small, depth = live["유형분류_중_의미"], live["유형분류_소_의미"], live["차수"]
    names = dict(zip(df["기관코드"], df["전체기관명"]))
    picks = [
        ("METRO_GOV", live[mid.eq("광역자치단체") & depth.eq("1")]),
        ("LOCAL_GOV", live[mid.eq("기초자치단체") & depth.eq("2") & small.isin(LOCAL_KINDS)]),
        ("METRO_EDU", live[mid.eq("시.도 교육청") & depth.eq("1")]),
        # 지역교육청 분류에 섞인 학교 부설 기관(예: 농업경영전문학교) 제외
        ("LOCAL_EDU", live[mid.eq("지역교육청") & depth.eq("2") & live["최하위기관명"].str.endswith("교육지원청")]),
        ("CENTRAL", live[mid.eq("중앙행정기관") & depth.eq("1") & small.isin(CENTRAL_KINDS)]),
        # 기타 범위(2026-10-27 사용자 결정): 국가행정조직 1차 중 중앙행정기관 분류 밖 — 대통령직속(기타)·분류 없음
        ("OTHER", live[depth.eq("1") & live["유형분류_대_의미"].eq("국가행정조직")
                       & ((mid.eq("중앙행정기관") & small.eq("대통령직속(기타)")) | mid.isna())]),
    ]
    edu_region = {}
    out = []
    for typ, rows in picks:
        for r in rows.itertuples(index=False):
            code, full = r.기관코드, r.전체기관명
            parent = names.get(r.차상위기관코드) if typ in ("LOCAL_GOV", "LOCAL_EDU") else None
            row = {"institution_id": code, "admin_code": code, "type": typ, "parent": parent,
                   "name": full, "status": "ok", "note": "", "source": "code.go.kr 기관코드"}
            if typ == "METRO_GOV":
                row["region"] = full
            elif typ == "LOCAL_GOV":
                row["region"] = parent
            elif typ == "METRO_EDU":
                row["region"] = edu_region[code] = full.removesuffix("교육청")
            elif typ == "LOCAL_EDU":
                row["name"] = r.최하위기관명
                row["region"] = edu_region.get(r.차상위기관코드)
            if typ == "CENTRAL" and not full.endswith(r.유형분류_소_의미.removeprefix("국무총리직속(").rstrip(")")):
                row.update(status="needs_review", note=f"분류 '{r.유형분류_소_의미}'와 명칭 불일치(임시 기구 여부 확인)")
            out.append(row)
    return out


# --- 2. 정부24 누리집 ---
def load_govkr(client: HttpClient, raw: Path) -> list[dict]:
    cache = raw / "govkr"
    cache.mkdir(parents=True, exist_ok=True)
    entries, page, last = [], 1, 1
    while page <= last:
        f = cache / f"page_{page:03d}.html"
        if not f.exists():
            r = client.get(GOVKR_URL, params={"Mcode": "11181", "pageIndex": page})
            r.raise_for_status()
            f.write_text(r.text, encoding="utf-8")
        page_entries, page_last = parse_govkr(f.read_text(encoding="utf-8"))
        entries += page_entries
        last = max(last, page_last)
        page += 1
    return entries


def parse_govkr(html: str) -> tuple[list[dict], int]:
    s = BeautifulSoup(html, "lxml")
    entries = []
    for li in s.select("ul.gov-web > li"):
        b, sp = li.select_one("dt b"), li.select_one("span")
        m = re.search(r"fncGoSite\('([^']+)'", str(li))
        if b and m:
            entries.append({"name": b.get_text(strip=True), "span": sp.get_text(strip=True).strip("()") if sp else "",
                            "url": m.group(1).strip()})
    pages = [int(x) for x in re.findall(r"pageIndex=(\d+)", html)]
    return entries, max(pages, default=1)


def clean(name: str) -> str:
    """'대한민국 국방부' → '국방부', '남원시 대표' → '남원시', '경찰청 대표 누리집' → '경찰청'"""
    name = re.sub(r"^대한민국\s+", "", name.strip())
    return re.sub(r"\s*(대표)?\s*(누리집|홈페이지)?$", "", name)


def norm(name: str) -> str:
    n = re.sub(r"\s+", "", clean(name)).replace("특례시", "시")
    return re.sub(r"(?<=[시군구도])청$", "", n)  # '종로구청' → '종로구', '경기도청' → '경기도'


def match_homepages(insts: list[dict], entries: list[dict]) -> None:
    by_name: dict[str, set] = {}
    by_span: dict[str, set] = {}
    for e in entries:
        keys = {norm(e["name"])}
        if e["span"] and not e["name"].startswith(e["span"]):
            # '고양특례시'(경기도) → '경기도고양시', '강원 춘천시'(강원특별자치도) → '강원특별자치도춘천시'
            keys.add(norm(e["span"] + clean(e["name"]).split()[-1]))
        for k in keys:
            by_name.setdefault(k, set()).add(e["url"])
        by_span.setdefault(norm(e["span"]), set()).add(e["url"])

    for inst in insts:
        key = norm(inst["name"])
        if inst["type"] == "LOCAL_EDU":
            key = None  # 정부24 목록에 교육지원청 없음
        urls, how = (by_name.get(key, set()), "") if key else (set(), "")
        if not urls and key:
            urls = by_span.get(key, set())
            urls = urls if len(urls) == 1 else set()
        if not urls and key:
            for new, olds in MERGED_ALIASES.items():
                if key.startswith(new):
                    cand = set().union(*(by_name.get(old + key[len(new):], set()) for old in olds))
                    if cand:
                        urls, how = cand, f"정부24 목록은 통합 전 명칭({'/'.join(olds)}) — URL 확인 필요"
        if len(urls) == 1:
            inst["homepage_url"] = urls.pop()
            if how:
                _review(inst, how)
        elif len(urls) > 1:
            inst["_candidates"] = sorted(urls)
            _review(inst, "정부24 누리집 후보 여러 개: " + " ".join(sorted(urls)))
        elif key:
            _review(inst, "홈페이지 미확보 (정부24 목록에서 못 찾음)")


# --- 3. 교육지원청 ---
PROVINCE = re.compile(r"^.*?(?:통합특별시|특별자치시|특별자치도|특별시|광역시|도)(?=.+교육지원청$)")
NEWSY = re.compile(r"[.,!?…\"“”'‘’]")  # 괄호 밖에 문장부호가 있으면 기사 제목으로 본다


def edu_links(html: str) -> list[tuple[str, str]]:
    """(공백 제거한 링크 문구, 절대 URL) — 문구가 '○○교육지원청' 으로 시작하는 메뉴 링크만(기사 제목 제외)."""
    out = []
    for raw_text, url, a in anchors(html):
        if not url:
            continue
        for text in (a.get_text(" ", strip=True), a.get("title") or ""):
            text = re.sub(r"\s+", "", text)
            if re.match(r"^[가-힣]+교육지원청", text) and not NEWSY.search(re.sub(r"\([^)]*\)", "", text)):
                out.append((text, url))
    return out


def collapse(urls: set[str]) -> set[str]:
    """같은 사이트의 '/x/' 와 '/x/main.do' 처럼 한쪽이 다른 쪽의 접두어면 짧은 쪽만 남긴다."""
    return {u for u in urls if not any(o != u and u.startswith(o) for o in urls)}


def short_edu_name(name: str) -> str:
    return PROVINCE.sub("", name)  # '서울특별시동부교육지원청' → '동부교육지원청'


def match_edu_offices(client: HttpClient, insts: list[dict], raw: Path) -> None:
    cache = raw / "edu"
    cache.mkdir(parents=True, exist_ok=True)
    links_by_parent: dict[str, list] = {}
    blocked: dict[str, bool] = {}
    for p in (i for i in insts if i["type"] == "METRO_EDU"):
        seeds = [p["homepage_url"]] if p.get("homepage_url") else p.get("_candidates", [])
        htmls = [fetch_followed(client, u, cache) for u in seeds]
        links_by_parent[p["name"]] = [l for h in htmls for l in edu_links(h)]
        blocked[p["name"]] = bool(htmls) and all(robots_blocked(h) for h in htmls)
    for inst in (i for i in insts if i["type"] == "LOCAL_EDU"):
        short = short_edu_name(inst["name"])
        urls = collapse({u for text, u in links_by_parent.get(inst["parent"], []) if text.startswith(short)})
        if len(urls) == 1:
            inst["homepage_url"] = urls.pop()
        elif urls:
            _review(inst, "시도교육청 누리집 링크 후보 여러 개: " + " ".join(sorted(urls)))
        elif blocked.get(inst["parent"]):
            _review(inst, "시도교육청 누리집 robots 비허용 — 링크 확인 불가")
        else:
            _review(inst, "시도교육청 누리집에서 링크 못 찾음")


def _review(inst: dict, why: str) -> None:
    inst["status"] = "needs_review"
    inst["note"] = "; ".join(x for x in (inst.get("note"), why) if x)


def exclude_without_homepage(insts: list[dict]) -> None:
    for i in insts:
        if not i.get("homepage_url"):
            i["status"] = "excluded"


# --- 실행 ---
def run(cfg: dict) -> dict:
    raw = Path(cfg["paths"]["raw"]) / "_phase0"
    raw.mkdir(parents=True, exist_ok=True)
    conn = db.connect(cfg["paths"]["state_db"])
    run_id = db.start_run(conn, "phase0")
    client = HttpClient(cfg["http"] | {"timeout_sec": 300})
    try:
        insts = select_institutions(load_codes(client, raw))
        match_homepages(insts, load_govkr(client, raw))
        match_edu_offices(client, insts, raw)
        exclude_without_homepage(insts)
        for inst in insts:
            db.upsert_institution(conn, inst)
        conn.commit()
        out = Path(cfg["paths"]["state_db"]).parent / "institutions.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, CSV_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(insts, key=lambda i: (i["type"], i["institution_id"])))
        summary = summarize(insts)
        db.finish_run(conn, run_id, "ok", str(summary["counts"]))
    except Exception as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    finally:
        client.close()
    print_summary(summary, out)
    return summary


def summarize(insts: list[dict]) -> dict:
    counts = {t: {"n": 0, "homepage": 0, "needs_review": 0, "excluded": 0} for t in EXPECTED}
    for i in insts:
        c = counts[i["type"]]
        c["n"] += 1
        c["homepage"] += bool(i.get("homepage_url"))
        if i["status"] in ("needs_review", "excluded"):
            c[i["status"]] += 1
    return {"counts": counts}


def print_summary(summary: dict, out: Path) -> None:
    print(f"→ {out}")
    print(f"{'type':<10}{'n':>5}{'예상':>6}{'차이':>6}{'홈페이지':>9}{'검토':>6}{'제외':>6}")
    for t, c in summary["counts"].items():
        print(f"{t:<10}{c['n']:>5}{EXPECTED[t]:>6}{c['n'] - EXPECTED[t]:>+6}{c['homepage']:>9}{c['needs_review']:>6}{c['excluded']:>6}")
