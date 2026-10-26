"""Phase 2 — 홈페이지 게시판 상세 분류 (BOARD found 기관만).

기관당 요청: 게시판 목록(캐시 재사용) + 게시글 최대 2건 + 저작권/이용약관 1쪽 + (직접 링크 PDF 가 있으면) 샘플 1개.
등급(5.2): C = robots 비허용·로그인·차단 / A = 목록에 기간 내 날짜(정적) + 직접 다운로드 / B = 그 외.
'수집 가능'(01 D-1, 2026-10-27 개정)은 등급 A·B + 약관상 자동수집 금지 없음.
공공누리는 1~4유형·표시 없음 모두 출처 표기 조건으로 사용 → license 는 출처 표기용으로 기록만 한다.
"""
import csv
import io
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pdfplumber
import yaml

from src import db
from src.http_client import HttpClient, RobotsDisallowed
from src.phase1_source_survey.survey import EXT, in_period, kogl_type
from src.phase3_collect.boards import adapter_for
from src.web import anchors, fetch_followed, robots_blocked

FINGERPRINTS = Path(__file__).with_name("cms_fingerprints.yaml")
USABLE_LICENSES = {f"공공누리 {n}유형" for n in range(1, 5)}
NO_KOGL = "공공누리 표시 없음"
POST_URL = re.compile(r"view|detail|read|nttId|nttSn|bbsSn|dataSid|articleNo|idx=|seq=|no=|/\d{3,}(?:$|[/?])", re.I)
DOWNLOAD = re.compile(r"down|atchFile|attach|fileSn|FileDown|getFile", re.I)
JS_DOWN = re.compile(r"fn\w*Down\w*\(|download\w*\(|fileDown\w*\(", re.I)
PAGE_PARAM = re.compile(r"[?&](pageIndex|page|pageNo|cpage|curPage|currentPage|pageNum|nowPage|pg|startPage|pageUnit)=", re.I)
TERMS_LINK = re.compile(r"저작권|이용약관|홈페이지\s*이용")
# '이메일무단수집거부'는 이메일 주소 수집 금지라 제외. 프로그램을 이용한 자료 수집 금지 문구만 본다.
TERMS_BAN = re.compile(r"(자동|프로그램|로봇|크롤링|스크래핑|기계적)[^.。]{0,40}(수집|복제)[^.。]{0,30}(금지|금합니다|할\s*수\s*없|불가)")
LOGIN = re.compile(r"로그인\s*(후|이\s*필요|하셔야)|login\.do|memberLogin", re.I)
REG_COLS = ["institution_id", "board_url", "cms_id", "list_pagination", "file_formats", "pdf_kind", "robots_allowed",
            "terms_ok", "license", "needs_js", "download_method", "crawl_grade", "posts_in_period", "note", "checked_at"]


def load_fingerprints(path: Path = FINGERPRINTS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def cms_of(url: str, html: str, fps: list[dict]) -> str:
    for fp in fps:
        m = fp.get("match") or {}
        if any(re.search(p, url) for p in m.get("url_regex", [])) or any(re.search(p, html) for p in m.get("html_regex", [])):
            return fp["id"]
    return "unknown"


def pagination(html: str) -> str:
    params = {m.group(1) for _, url, a in anchors(html) for m in [PAGE_PARAM.search((url or "") + (a.get("onclick") or ""))] if m}
    if params:
        return ",".join(sorted(params))
    return "js" if re.search(r"(goPage|fn_?link_?page|fnGoPage|linkPage)\s*\(", html, re.I) else ""


def post_links(html: str, board_url: str, limit: int = 2) -> list[str]:
    host = urlsplit(board_url).netloc
    base_q = parse_qs(urlsplit(board_url).query)
    board_dir = urlsplit(board_url).path.rsplit("/", 1)[0]
    out = []
    for text, url, _ in anchors(html):
        if not url or urlsplit(url).netloc != host or url in out or url.rstrip("/") == board_url.rstrip("/"):
            continue
        same_list = urlsplit(url).path == urlsplit(board_url).path and parse_qs(urlsplit(url).query) == base_q
        if len(text) >= 6 and POST_URL.search(url) and not PAGE_PARAM.search(url) and not same_list:
            out.append(url)
    # 게시판 경로 아래 링크(실제 게시글)를 메뉴의 'detail' 류 링크보다 먼저
    out.sort(key=lambda u: not urlsplit(u).path.startswith(board_dir))
    return out[:limit]


def attachments(html: str) -> tuple[set[str], str, list[str]]:
    """(확장자들, 다운로드 방식, 직접 링크 PDF URL들)"""
    exts, methods, pdfs = set(), set(), []
    for text, url, a in anchors(html):
        blob = f"{text} {a.get('href') or ''} {a.get('onclick') or ''}"
        e = {x.lower() for x in EXT.findall(blob)} & {"xlsx", "xls", "csv", "pdf", "hwp", "hwpx", "zip", "jpg", "png"}
        if not e and not DOWNLOAD.search(blob):
            continue
        exts |= e
        if url and (DOWNLOAD.search(url) or EXT.search(url)):
            methods.add("direct")
            if "pdf" in e:
                pdfs.append(url)
        elif JS_DOWN.search(blob) or (a.get("href") or "").lower().startswith("javascript:"):
            methods.add("js")
    if re.search(r"<form[^>]+method=[\"']?post[^>]*>[\s\S]{0,2000}(fileSn|atchFile|download)", html, re.I):
        methods.add("post")
    method = "direct" if "direct" in methods else ("post" if "post" in methods else ("js" if "js" in methods else ""))
    return exts, method, pdfs


def pdf_kind_of(data: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception:
        return "n/a"
    return "text" if len(text.strip()) > 50 else "scanned"


def terms_check(client: HttpClient, home: str, cache: Path) -> tuple[str, str]:
    links = [(t, u) for t, u, _ in anchors(home) if u and TERMS_LINK.search(t)][:2]
    if not links:
        return "unknown", "저작권/이용약관 링크 못 찾음"
    for t, u in links:
        html = fetch_followed(client, u, cache)
        if robots_blocked(html):
            continue
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        m = TERMS_BAN.search(txt)
        if m:
            return "no", f"약관: …{m.group(0)[:60]}…"
    return "yes", f"약관 '{links[0][0][:15]}' 확인 — 자동수집 금지 문구 없음"


def classify(client: HttpClient, inst: dict, board_url: str, start: date, end: date, cache: Path, fps: list[dict]) -> dict:
    r = {"institution_id": inst["institution_id"], "board_url": board_url}
    notes = []
    html = fetch_followed(client, board_url, cache)
    if robots_blocked(html):
        return r | {"robots_allowed": "no", "crawl_grade": "C", "note": "게시판 robots 비허용"}
    r["robots_allowed"] = "yes"
    r["cms_id"] = cms_of(board_url, html, fps)
    adapter = adapter_for(board_url)
    if adapter:  # CMS 어댑터가 있으면 게시글 목록·첨부를 정확히 읽는다
        r["cms_id"] = adapter.ID
        posts = adapter.list_posts(html, board_url)
        r["list_pagination"] = f"{adapter.page_url(board_url, 2)} (보이는 마지막 {adapter.last_page(html)}쪽)"
        dates = [d for p in posts if p["date"] and start <= (d := date.fromisoformat(p["date"])) <= end]
        targets = [] if adapter.INLINE else [p["url"] for p in posts[:2]]
    else:
        r["list_pagination"] = pagination(html)
        dates = in_period(re.sub(r"<[^>]+>", " ", html), start, end)
        targets = post_links(html, board_url)
    r["needs_js"] = "no" if dates else "yes"
    r["posts_in_period"] = len(dates)
    login = bool(LOGIN.search(html)) and not dates
    exts, method, pdfs = (set(), "", []) if adapter else attachments(html)  # 어댑터면 게시글 첨부만 본다
    if adapter and adapter.INLINE:  # 목록 HTML 자체가 원본(첨부 없음)
        exts, method = {"html"}, "direct"
    lic = kogl_type(html)
    for p in targets:
        ph = fetch_followed(client, p, cache)
        if robots_blocked(ph):
            notes.append("게시글 경로 robots 비허용")
            r["robots_allowed"] = "no"
            break
        if adapter:
            files = adapter.list_attachments(ph, p)
            blocked = [f["url"] for f in files if not client.allowed(f["url"])]
            if blocked:
                notes.append("첨부 경로 robots 비허용")
                r["robots_allowed"] = "no"
            e, m, pp = {f["ext"] for f in files}, ("direct" if files else ""), [f["url"] for f in files if f["ext"] == "pdf"]
        else:
            e, m, pp = attachments(ph)
        exts |= e
        method = method or m
        pdfs += pp
        lic = lic or kogl_type(ph)
    if adapter and not lic:
        notes.append("목록 본문(INLINE) 확인 — 공공누리 표시 없음" if adapter.INLINE
                     else f"게시글 {len(targets)}건 확인 — 공공누리 표시 없음")
    r["file_formats"] = ",".join(sorted(exts))
    r["download_method"] = method or ("js" if exts else None)  # 첨부 흔적 없으면 미확인(NULL)
    r["license"] = lic
    r["pdf_kind"] = "n/a"
    if pdfs:
        try:
            resp = client.get(pdfs[0])
            r["pdf_kind"] = pdf_kind_of(resp.content) if resp.status_code == 200 else "n/a"
        except RobotsDisallowed:
            r["robots_allowed"] = "no"
            notes.append("첨부 경로 robots 비허용")
    elif "pdf" in exts:
        notes.append("PDF 직접 링크 없음 — 성격 미확인")
    home = fetch_followed(client, inst["homepage_url"], cache)
    r["terms_ok"], tnote = terms_check(client, home, cache)
    notes.append(tnote)
    if r["robots_allowed"] == "no" or login:
        r["crawl_grade"] = "C"
        notes.append("로그인 필요" if login else "")
    elif r["needs_js"] == "no" and r["download_method"] in ("direct", None):
        r["crawl_grade"] = "A"
    else:
        r["crawl_grade"] = "B"
    # 표시 없는 자료도 출처 표기로 사용(01, 2026-10-27 (나)). 유형은 출처 표기용으로만 기록
    r["license"] = r["license"] or NO_KOGL
    collectable = r["crawl_grade"] in ("A", "B") and r["terms_ok"] != "no"
    notes.append("수집 가능" if collectable else "수집 보류(" + ", ".join(
        x for x, bad in [("등급 C", r["crawl_grade"] == "C"), ("약관", r["terms_ok"] == "no")] if bad) + ")")
    r["note"] = " · ".join(n for n in notes if n)
    return r


def run(cfg: dict, pilot: bool) -> None:
    from src.phase1_source_survey.survey import pilot_ids
    conn = db.connect(cfg["paths"]["state_db"])
    q = """SELECT i.*, s.url AS board_url FROM source_survey s JOIN institutions i USING (institution_id)
           WHERE s.source='BOARD' AND s.status='found' AND i.status='ok'"""
    ids = pilot_ids(cfg) if pilot else []
    if pilot:
        q += f" AND i.institution_id IN ({','.join('?' * len(ids))})"
    targets = [dict(r) for r in conn.execute(q, ids)]
    done = {r[0] for r in conn.execute("SELECT institution_id FROM board_registry")}
    run_id = db.start_run(conn, "phase2", "--pilot" if pilot else "")
    client = HttpClient(cfg["http"] | {"timeout_sec": 120})
    start, end = date.fromisoformat(cfg["period"]["start"]), date.fromisoformat(cfg["period"]["end"])
    cache, fps = Path(cfg["paths"]["raw"]) / "_phase1" / "pages", load_fingerprints()
    try:
        for t in targets:
            if t["institution_id"] in done:
                continue
            r = classify(client, t, t["board_url"], start, end, cache, fps) | {"checked_at": db.now()}
            conn.execute(f"INSERT OR REPLACE INTO board_registry ({','.join(REG_COLS)}) VALUES ({','.join('?' * len(REG_COLS))})",
                         [r.get(c) for c in REG_COLS])
            conn.commit()
            print(f"  {t['institution_id']} {t['name']}: {r.get('crawl_grade')} {r.get('cms_id')} {r.get('file_formats')}", flush=True)
        rows = [dict(r) for r in conn.execute("SELECT * FROM board_registry ORDER BY institution_id")]
        with open(Path(cfg["paths"]["state_db"]).parent / "board_registry.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, REG_COLS)
            w.writeheader()
            w.writerows(rows)
        db.finish_run(conn, run_id, "ok", f"{len(rows)} boards")
        print_summary(rows)
    except Exception as e:
        db.finish_run(conn, run_id, "failed", repr(e))
        raise
    finally:
        client.close()


def url_signature(url: str) -> str:
    """미분류 게시판 묶기용: 호스트 제거, 숫자·긴 ID 를 *, 쿼리는 키만. 예) /site/*/bbs/list.do?bbsId&menu"""
    p = urlsplit(url)
    path = re.sub(r"\d+", "*", p.path)
    path = re.sub(r"/[A-Za-z]{2,}(?:_[A-Za-z0-9*]+)?\*", "/*", path)
    keys = "&".join(sorted(parse_qs(p.query).keys()))
    return path + (f"?{keys}" if keys else "")


def summarize(rows: list[dict]) -> dict:
    from collections import Counter
    fmt = Counter(f for r in rows for f in (r["file_formats"] or "").split(",") if f)
    unknown = Counter(url_signature(r["board_url"]) for r in rows if r["cms_id"] in ("unknown", None) and r["board_url"])
    return {"cms": Counter(r["cms_id"] for r in rows), "grade": Counter(r["crawl_grade"] for r in rows),
            "formats": fmt, "collectable": sum("수집 가능" in (r["note"] or "") for r in rows),
            "unknown_clusters": unknown}


def print_summary(rows: list[dict]) -> None:
    s = summarize(rows)
    print(f"게시판 {len(rows)}곳 · 수집 가능 {s['collectable']}곳")
    for k in ("cms", "grade", "formats"):
        print(f"  {k}: " + ", ".join(f"{a}={n}" for a, n in s[k].most_common()))
    print("  미분류 URL 묶음(2곳 이상): " + ", ".join(f"{a}={n}" for a, n in s["unknown_clusters"].most_common() if n > 1))
