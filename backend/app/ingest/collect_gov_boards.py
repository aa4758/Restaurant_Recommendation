"""구청 업무추진비 사전공표 게시판 수집 → 정규화 CSV(load_gov_expense 입력).

    python -m app.ingest.collect_gov_boards gwanak|guro [--since YYYY-MM-DD]

01 크롤링 예외 조건: robots.txt 준수(* 그룹·와일드카드), 요청 간격 3초 이상(Crawl-delay 가 더 길면 그것),
로그인·우회 없음, 응답은 data/raw/gov_expense/cache/ 에 캐시(재실행 시 재요청 안 함), 공공누리 3·4유형 보류.
PII(사용자·집행목적 원문)는 파싱 단계에서 버리고 COLUMNS 만 남김.
- gwanak: HTML 카드(estimateList.do), 장소에 도로명 주소 포함.
- guro: 게시글 PDF 첨부(표: 사용자·일시·장소·집행목적·대상인원·금액·결제방법·비목), 장소는 상호만.
  HWP 첨부는 파서 없음 → 건수만 집계(skipped_hwp).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from .load_gov_expense import COLUMNS, RAW_DIR, default_since

UA = "JJINMAT-collector/0.1 (public expense disclosure)"
DELAY = 3.0


def robots_allowed(txt: str, path: str, agent: str = "*") -> bool:
    """robots.txt 판정(가장 긴 규칙 우선, * · $ 지원). urllib.robotparser 는 와일드카드를 몰라서 직접 구현."""
    groups, cur, in_ua = [], None, False
    for line in re.sub(r"</?pre>", "", txt).splitlines():
        k, _, v = line.split("#")[0].partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if not in_ua:
                cur = ([], [])
                groups.append(cur)
            cur[0].append(v.lower())
            in_ua = True
        elif k in ("allow", "disallow") and cur is not None:
            cur[1].append((k == "allow", v))
            in_ua = False
        else:
            in_ua = False
    best = (-1, True)
    for agents, rules in groups:
        if agent not in agents:
            continue
        for ok, p in rules:
            pat = re.escape(p).replace(r"\*", ".*")
            if pat.endswith(r"\$"):
                pat = pat[:-2] + "$"
            if p and re.match(pat, path) and (len(p), ok) > best:
                best = (len(p), ok)
    return best[1]


def crawl_delay(txt: str) -> float:
    m = re.search(r"(?im)^\s*crawl-delay\s*:\s*([\d.]+)", txt)
    return float(m.group(1)) if m else 0.0


class Fetcher:
    """사이트 1곳 전용: robots 확인 → (첨부만) 캐시 → 간격 유지 후 요청. 목록·robots 는 매번 새로 받음."""

    def __init__(self, base: str, cache_dir: Path, opener=urllib.request.urlopen, sleep=time.sleep):
        self.base, self.cache, self.opener, self.sleep, self.last = base, Path(cache_dir), opener, sleep, 0.0
        self.delay, self.requests = DELAY, 0
        self.cache.mkdir(parents=True, exist_ok=True)
        self.robots = self._get(urllib.parse.urljoin(base, "/robots.txt"), cache=False).decode("utf-8", "replace")
        self.delay = max(DELAY, crawl_delay(self.robots))

    def _get(self, url: str, cache: bool = True) -> bytes:
        f = self.cache / hashlib.sha1(url.encode()).hexdigest()
        if cache and f.exists():
            return f.read_bytes()
        self.sleep(max(0.0, self.last + self.delay - time.monotonic()))
        with self.opener(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as resp:
            body = resp.read()
        self.last = time.monotonic()
        self.requests += 1
        if cache:
            f.write_bytes(body)
        return body

    def get(self, url: str, cache: bool = True) -> bytes:
        url = urllib.parse.urljoin(self.base, html.unescape(url))
        u = urllib.parse.urlsplit(url)
        if not robots_allowed(self.robots, u.path + ("?" + u.query if u.query else "")):
            raise PermissionError(f"robots.txt 금지: {url}")
        return self._get(url, cache)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# ---- 관악구: HTML 카드 ----
GWANAK = "https://www.gwanak.go.kr"
GWANAK_LIST = "/site/gwanak/estimate/estimateList.do?pageIndex={page}&recordCountPerPage=100"
GWANAK_SOURCE = "관악구 업무추진비"


def parse_gwanak(page_html: str) -> list[dict]:
    rows = []
    for table in re.findall(r'<table class="view">(.*?)</table>', page_html, re.S):
        cells = dict((_text(k), _text(v)) for k, v in
                     re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", table, re.S))
        rows.append({"exec_dt": cells.get("집행일시", "")[:16], "agency": "서울특별시 관악구",
                     "dept": cells.get("집행부서", ""), "place": cells.get("집행장소", ""),
                     "amount": cells.get("집행금액(원)", "").replace(",", ""), "category": cells.get("비목", ""),
                     "source": GWANAK_SOURCE})  # 집행내역·사용자 버림
    return rows


def collect_gwanak(f: Fetcher, since: str) -> tuple[list[dict], dict]:
    out, page = [], 1
    while True:
        rows = parse_gwanak(f.get(GWANAK_LIST.format(page=page), cache=False).decode("utf-8", "replace"))
        out += [r for r in rows if r["exec_dt"][:10] >= since]
        if not rows or max(r["exec_dt"][:10] for r in rows) < since:  # 최신순 → 창 밖이면 끝
            return out, {"pages": page}
        page += 1


# ---- 구로구: 게시글 PDF ----
GURO = "https://www.guro.go.kr"
GURO_LIST = "/www/selectBbsNttList.do?bbsNo=655&key=1732&pageUnit=100&pageIndex={page}"
GURO_SOURCE = "구로구 업무추진비"
_GURO_ROW = re.compile(r'<a href="(\./selectBbsNttView[^"]*)"[^>]*>(.*?)</a>.*?<time datetime="([\d-]+)"(.*?)</tr>', re.S)


def parse_guro_list(page_html: str) -> list[dict]:
    """목록 → [{title, posted, files:[(url, ext)]}]."""
    posts = []
    for _, title, posted, rest in _GURO_ROW.findall(page_html):
        files = re.findall(r'href="(downloadBbsFile\.do[^"]*)"[^>]*><span class="p-icon p-icon__(\w+)"', rest)
        posts.append({"title": _text(title), "posted": posted, "files": [("/www/" + u, ext) for u, ext in files]})
    return posts


def guro_dept(title: str) -> str:
    m = re.search(r"\d+\s*월\s*(?:분\s*)?(\S+)", title)
    return m.group(1) if m else title


def parse_guro_pdf(path, dept: str) -> list[dict]:
    """PDF 표 → 정규화 행. 헤더(일시·장소·금액) 있는 표부터, 이후 쪽의 헤더 없는 표는 같은 열 순서로 이어 읽음."""
    import pdfplumber  # 수집 전용 의존성

    rows, cols = [], None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [re.sub(r"\s+", " ", c or "").strip() for c in raw]
                    head = [c.replace(" ", "") for c in cells]
                    if "일시" in head and "장소" in head and "금액" in head:
                        cols = {k: head.index(k) for k in ("일시", "장소", "금액")}
                        cols["비목"] = head.index("비목") if "비목" in head else None
                        continue
                    if not cols or len(cells) <= max(v for v in cols.values() if v is not None):
                        continue
                    dt = cells[cols["일시"]]
                    if not re.match(r"\d{4}-\d{2}-\d{2}", dt):
                        continue  # 합계 행 등
                    rows.append({"exec_dt": dt[:16], "agency": "서울특별시 구로구", "dept": dept,
                                 "place": cells[cols["장소"]], "amount": cells[cols["금액"]].replace(",", ""),
                                 "category": cells[cols["비목"]] if cols["비목"] is not None else "",
                                 "source": GURO_SOURCE})  # 사용자·집행목적 버림
    return rows


def collect_guro(f: Fetcher, since: str) -> tuple[list[dict], dict]:
    out, page, info = [], 1, {"posts": 0, "pdf": 0, "skipped_hwp": 0, "other": 0, "pdf_errors": 0}
    while True:
        posts = parse_guro_list(f.get(GURO_LIST.format(page=page), cache=False).decode("utf-8", "replace"))
        for p in posts:
            if p["posted"] < since:
                continue
            info["posts"] += 1
            for url, ext in p["files"]:
                if ext != "pdf":
                    info["skipped_hwp" if ext.startswith("hwp") else "other"] += 1
                    continue
                info["pdf"] += 1
                try:
                    out += parse_guro_pdf(io.BytesIO(f.get(url)), guro_dept(p["title"]))
                except Exception:  # 깨진 PDF 1건 때문에 전체를 멈추지 않음(건수 기록)
                    info["pdf_errors"] += 1
        if not posts or max(p["posted"] for p in posts) < since:
            info["pages"] = page
            return [r for r in out if r["exec_dt"][:10] >= since], info
        page += 1


BOARDS = {"gwanak": (GWANAK, collect_gwanak), "guro": (GURO, collect_guro)}


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="구청 업무추진비 게시판 수집(정규화 CSV)")
    ap.add_argument("board", choices=sorted(BOARDS))
    ap.add_argument("--since", default=None, help="이 날짜 이후(기본: 2년 전 같은 달 1일)")
    args = ap.parse_args()
    since = args.since or default_since()
    base, collect = BOARDS[args.board]
    t0 = time.monotonic()
    f = Fetcher(base, RAW_DIR / "cache" / args.board)
    rows, info = collect(f, since)
    path = write_csv(rows, RAW_DIR / f"{args.board}_{date.today():%Y%m%d}.csv")
    print(f"[ok]   {len(rows):,}행 → {path} · 요청 {f.requests:,}회 · {time.monotonic() - t0:,.0f}초 · {info}")


if __name__ == "__main__":
    main()
