"""Phase 1 — 기관별 수집 출처 조사 (DATAGOKR / BOARD / OPENGOKR).

- DATAGOKR: 공공데이터포털 '목록 메타정보' 파일(행정안전부, 15121937, 이용허락 제한 없음)을 1회 받아 로컬에서 검색.
  검색 페이지를 반복 조회하지 않는다. 제공기관코드 = 행정기관코드라 기관 매칭은 코드로 정확히.
  데이터셋별 이용허락범위는 상세 페이지 1회 조회로 기록.
- BOARD: 홈페이지(리다이렉트 추적) 메뉴에서 '업무추진비' 링크 → 목록 페이지에 수집 기간 내 날짜가 있으면 found.
  없으면 사이트맵·사전정보공표 페이지(2단계까지)에서 찾는다. 인트로 첫 화면이면 메인 페이지로 옮겨 본다. 기관당 요청 수를 작게 유지(9절).
- OPENGOKR: open.go.kr robots 가 루트 외 전부 비허용 → 자동 조회 안 하고 needs_review 로 기록.
"""
import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from bs4 import BeautifulSoup

from src import db
from src.http_client import HttpClient
from src.web import anchors, blocked_reason, fetch_followed, final_url, main_candidates, robots_blocked

META_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000003671255&fileDetailSn=1&insertDataPrcus=N"
META_FILE = "datagokr_meta_15121937.csv"
EXPENSE = re.compile(r"업무\s*추진비|업추비")
SCOPES = [  # 제목 → 공개 범위 (위에서부터 첫 일치)
    (r"지방재정365", "지방재정365 예산 편성·비율(집행내역 아님)"),
    (r"의회|의원", "의회"),
    (r"출자출연", "출자출연기관"),
    (r"상수도|사업본부|사업소", "사업소"),
    (r"단체장|기관장|장·차관", "기관장"),
    (r"임원", "임원"),
]
NAV = re.compile(r"사이트\s*맵|전체\s*메뉴|사전\s*정보\s*공[표개]|정보\s*공개|재정\s*공개")
NAV_SKIP = re.compile(r"청구|제도|서식|법령|이용\s*안내|학원|교습소|계약|신고|시스템")  # 업무추진비 목록이 아닌 정보공개 하위 메뉴
KOGL = re.compile(r"공공누리\s*(?:제\s*)?([1-4])\s*유형|(?:opentype|kogl_?type|img_open_?type)_?0?([1-4])", re.I)
DATE = re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})")
EXT = re.compile(r"\.(xlsx|xls|csv|pdf|hwpx|hwp|zip|jpg|png)\b", re.I)
SURVEY_COLS = ["institution_id", "source", "available", "url", "coverage_from", "coverage_to", "scope", "formats",
               "license", "priority", "status", "note", "checked_at"]
PRIORITY = {"DATAGOKR": 1, "BOARD": 2, "OPENGOKR": 3}


# --- DATAGOKR ---
def load_meta(client: HttpClient, raw: Path) -> pd.DataFrame:
    f = raw / META_FILE
    if not f.exists():
        r = client.get(META_URL)
        r.raise_for_status()
        f.write_bytes(r.content)
    df = pd.read_csv(f, encoding="cp949", dtype=str)
    df.columns = [c.replace(" ", "") for c in df.columns]  # '서비스 유형' → '서비스유형'
    return df


def scope_of(title: str) -> str:
    return next((s for pat, s in SCOPES if re.search(pat, title)), "")


def datagokr_rows(inst: dict, meta: pd.DataFrame, license_of) -> list[dict]:
    hits = meta[(meta["제공기관코드"] == inst["institution_id"])
                & (meta["목록명"].str.contains(EXPENSE, na=False) | meta["키워드"].str.contains(EXPENSE, na=False))]
    if hits.empty:
        return [{"source": "DATAGOKR", "available": "no", "url": "", "status": "not_found"}]
    rows = []
    for h in hits.itertuples(index=False):
        kind = "openapi" if h.목록유형 == "API" else "fileData"
        url = f"https://www.data.go.kr/data/{h.목록키}/{kind}.do"
        scope = scope_of(h.목록명)
        usable = not scope.startswith("지방재정365")
        rows.append({"source": "DATAGOKR", "url": url, "scope": scope, "formats": (h.데이터포맷 or "").lower(),
                     "available": "yes" if usable else "no", "status": "found" if usable else "not_found",
                     "license": license_of(url) if usable else "",
                     "note": f"{h.목록명} · {h.목록유형}/{h.서비스유형} · 주기 {h.주기}"})
    return rows


def datagokr_license(client: HttpClient, cache: Path):
    def get(url: str) -> str:
        html = fetch_followed(client, url, cache)
        txt = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" "))
        m = re.search(r"이용허락범위\s*([^\s].{0,30}?)(?:\s{2,}|$| 데이터| 키워드| 등록)", txt)
        k = KOGL.search(txt)
        return " ".join(x for x in (m and m.group(1).strip(), k and f"공공누리 {k.group(1) or k.group(2)}유형") if x)
    return get


# --- BOARD ---
def in_period(text: str, start: date, end: date) -> list[date]:
    out = []
    for y, m, d in DATE.findall(text):
        try:
            dt = date(int(y), int(m), int(d))
        except ValueError:
            continue
        if start <= dt <= end:
            out.append(dt)
    return out


def kogl_type(html: str) -> str:
    k = KOGL.search(html)
    return f"공공누리 {k.group(1) or k.group(2)}유형" if k else ""


def expense_links(html: str) -> list[tuple[str, str]]:
    """'업무추진비' 링크. 사전정보공표 목록처럼 링크 문구가 '바로가기'뿐이면 짧은 행(tr/li) 글자로 판단."""
    seen, out = set(), []
    for text, url, a in anchors(html):
        if not url or url in seen or "open.go.kr" in url:
            continue
        if not EXPENSE.search(text) and (row := a.find_parent(["tr", "li"])):
            text = row.get_text(" ", strip=True)
            text = text if len(text) < 150 else ""
        if EXPENSE.search(text):
            seen.add(url)
            out.append((text, url))
    return out


def nav_links(html: str) -> list[str]:
    """같은 호스트의 사이트맵·사전정보공표·정보공개 링크(사이트맵 > 사전정보공표 > 그 외 순)."""
    host = urlsplit(final_url(html) or "").hostname
    found = {}
    for text, url, _ in anchors(html):
        if url and NAV.search(text) and not NAV_SKIP.search(text) and urlsplit(url).hostname == host:
            rank = 0 if re.search(r"사이트\s*맵|전체\s*메뉴", text) else 1 if re.search(r"사전\s*정보", text) else 2
            found[url] = min(rank, found.get(url, 9))
    return sorted(found, key=found.get)


def find_board(client: HttpClient, inst: dict, cache: Path, start: date, end: date, max_pages: int = 6) -> dict:
    home = fetch_followed(client, inst["homepage_url"], cache)
    if robots_blocked(home):
        return {"available": "unknown", "url": inst["homepage_url"], "status": "needs_review",
                "note": f"홈페이지 접근 불가: {blocked_reason(home)} — 자동 조사 안 함 (등급 C 후보)"}
    if sum(1 for _ in anchors(home)) < 30:  # 인트로·JS 첫 화면이면 실제 메인 페이지로
        for url in main_candidates(home)[:2]:
            page = fetch_followed(client, url, cache)
            if not robots_blocked(page) and sum(1 for _ in anchors(page)) >= 30:
                home = page
                break
    queue = expense_links(home)
    if not queue:  # 메뉴에 없으면 사이트맵·사전정보공표에서, 그래도 없으면 그 페이지들의 하위 메뉴 한 단계 더
        todo, seen = nav_links(home)[:4], set()
        for depth in (1, 2):
            nxt = []
            for url in todo:
                seen.add(url)
                page = fetch_followed(client, url, cache)
                if robots_blocked(page):
                    continue
                queue += [l for l in expense_links(page) if l[1] not in {u for _, u in queue}]
                nxt += [u for u in nav_links(page)[:3] if u not in seen and u not in nxt]
            if queue:
                break
            todo = nxt[:3]
    tried, best = 0, None
    while queue and tried < max_pages:
        text, url = queue.pop(0)
        html = fetch_followed(client, url, cache)
        tried += 1
        if robots_blocked(html):
            best = best or {"url": url, "dates": [], "html": "", "robots": True, "text": text}
            continue
        dates = in_period(BeautifulSoup(html, "lxml").get_text(" "), start, end)
        cand = {"url": final_url(html) or url, "dates": dates, "html": html, "robots": False, "text": text}
        if dates and (not best or len(dates) > len(best["dates"])):
            best = cand
        elif not best:
            best = cand
        if not dates:  # 안내/탭 페이지면 한 단계 더
            queue += [l for l in expense_links(html) if l[1] not in {u for _, u in queue}]
    if not best:
        return {"available": "unknown", "url": "", "status": "needs_review", "note": f"홈페이지·사이트맵에서 '업무추진비' 링크 못 찾음 (조회 {tried}쪽)"}
    if best["robots"]:
        return {"available": "unknown", "url": best["url"], "status": "needs_review", "note": "게시판 경로 robots 비허용 (등급 C 후보)"}
    exts = sorted({e.lower() for e in EXT.findall(best["html"])} & {"xlsx", "xls", "csv", "pdf", "hwp", "hwpx", "zip"})
    d = sorted(best["dates"])
    found = bool(d)
    return {"available": "yes" if found else "unknown", "url": best["url"], "status": "found" if found else "needs_review",
            "coverage_from": d[0].isoformat() if d else None, "coverage_to": d[-1].isoformat() if d else None,
            "formats": ",".join(exts), "license": kogl_type(best["html"]),
            "note": f"메뉴 '{best['text'][:30]}' · 1쪽 날짜 {len(d)}건" + ("" if found else " — 기간 내 날짜 없음(JS 렌더링·별도 탭 가능)")}


# --- 실행 ---
def pilot_ids(cfg: dict) -> list[str]:
    return [str(x) for x in cfg["pilot"]["institutions"]]


def run(cfg: dict, pilot: bool) -> None:
    raw = Path(cfg["paths"]["raw"]) / "_phase1"
    raw.mkdir(parents=True, exist_ok=True)
    conn = db.connect(cfg["paths"]["state_db"])
    where = "status = 'ok'" + (f" AND institution_id IN ({','.join('?' * len(pilot_ids(cfg)))})" if pilot else "")
    insts = [dict(r) for r in conn.execute(f"SELECT * FROM institutions WHERE {where}", pilot_ids(cfg) if pilot else [])]
    done = {r[0] for r in conn.execute("SELECT DISTINCT institution_id FROM source_survey")}
    run_id = db.start_run(conn, "phase1", "--pilot" if pilot else "")
    client = HttpClient(cfg["http"] | {"timeout_sec": 120})
    start, end = date.fromisoformat(cfg["period"]["start"]), date.fromisoformat(cfg["period"]["end"])
    try:
        meta = load_meta(client, raw)
        lic = datagokr_license(client, raw / "pages")
        opengokr_ok = client.allowed("https://www.open.go.kr/othicInfo/infoList/orginlInfoList.do")
        for inst in insts:
            if inst["institution_id"] in done:  # 이어하기: 이미 조사한 기관은 건너뜀
                continue
            rows = datagokr_rows(inst, meta, lic)
            rows.append({"source": "BOARD", **find_board(client, inst, raw / "pages", start, end)})
            rows.append({"source": "OPENGOKR", "available": "unknown", "url": "https://www.open.go.kr/",
                         "status": "needs_review" if not opengokr_ok else "not_found",
                         "note": "open.go.kr robots 비허용(루트만 허용) — 자동 조회 안 함" if not opengokr_ok else "자동 조회 미구현"})
            for r in rows:
                save_row(conn, inst["institution_id"], r)
            conn.commit()
            print(f"  {inst['institution_id']} {inst['name']}: " + ", ".join(f"{r['source']}={r['status']}" for r in rows), flush=True)
        out = export(conn, Path(cfg["paths"]["state_db"]).parent, Path(cfg["paths"]["output"]),
                     pilot_ids(cfg) if pilot else None)
        db.finish_run(conn, run_id, "ok", str(out))
    except Exception as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    finally:
        client.close()
    print_summary(out)


def save_row(conn, inst_id: str, r: dict) -> None:
    row = {c: r.get(c) for c in SURVEY_COLS} | {"institution_id": inst_id, "url": r.get("url") or "",
                                                 "priority": PRIORITY[r["source"]], "checked_at": db.now()}
    conn.execute(f"INSERT OR REPLACE INTO source_survey ({','.join(SURVEY_COLS)}) VALUES ({','.join('?' * len(SURVEY_COLS))})",
                 [row[c] for c in SURVEY_COLS])


def export(conn, data_dir: Path, out_dir: Path, only: list[str] | None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(r) for r in conn.execute("SELECT * FROM source_survey ORDER BY institution_id, priority, url")]
    with open(data_dir / "source_survey.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, SURVEY_COLS)
        w.writeheader()
        w.writerows(rows)
    insts = {r["institution_id"]: dict(r) for r in conn.execute("SELECT * FROM institutions WHERE status='ok'")}
    surveyed = {r["institution_id"] for r in rows}
    found = {r["institution_id"] for r in rows if r["status"] == "found"}
    foi = sorted(surveyed - found)
    with open(out_dir / "foi_candidates.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["institution_id", "name", "type", "homepage_url", "reason"])
        for i in foi:
            notes = "; ".join(f"{r['source']}:{r['note'] or r['status']}" for r in rows if r["institution_id"] == i)
            w.writerow([i, insts[i]["name"], insts[i]["type"], insts[i]["homepage_url"], notes])
    by_source = {}
    for r in rows:
        s = by_source.setdefault(r["source"], {})
        s[r["status"]] = s.get(r["status"], 0) + 1
    return {"surveyed": len(surveyed), "with_found": len(found), "foi": foi, "by_source_status": by_source}


def print_summary(s: dict) -> None:
    print(f"조사 {s['surveyed']}곳 · 출처 1개 이상 found {s['with_found']}곳 · 정보공개청구 후보 {len(s['foi'])}곳")
    for src, st in s["by_source_status"].items():
        print(f"  {src}: {st}")
